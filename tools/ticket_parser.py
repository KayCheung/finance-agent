"""
tools/ticket_parser.py
多票据类型差异化解析器 - Ticket_Parser

支持票据类型：增值税专用发票、增值税普通发票、电子发票、火车票、机票行程单、出租车票、过路费发票
每种票据类型有独立的字段提取规则和校验规则。
parse(format(ticket)) 往返一致性是关键正确性属性。

需求: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8
"""
import re
from agent_core.models import TicketType, ParsedTicket


# ── 各票据类型的字段定义 ──

VAT_SPECIAL_FIELDS = [
    "invoice_code", "invoice_number", "invoice_date",
    "buyer_name", "buyer_tax_id", "seller_name", "seller_tax_id",
    "amount", "tax_rate", "tax_amount", "total",
]

VAT_NORMAL_FIELDS = [
    "invoice_code", "invoice_number", "invoice_date",
    "buyer_name", "seller_name",
    "amount", "tax_rate", "tax_amount", "total",
]

ELECTRONIC_FIELDS = [
    "invoice_code", "invoice_number", "invoice_date",
    "buyer_name", "seller_name",
    "amount", "tax_rate", "tax_amount", "total",
]

TRAIN_FIELDS = [
    "passenger_name", "departure_station", "arrival_station",
    "train_number", "seat_class", "ticket_price", "travel_date",
]

FLIGHT_FIELDS = [
    "passenger_name", "flight_number", "departure", "destination",
    "ticket_price", "fuel_surcharge", "civil_aviation_fund",
    "total", "travel_date",
]

TAXI_FIELDS = [
    "pickup_time", "dropoff_time", "amount", "mileage",
]

TOLL_FIELDS = [
    "toll_station", "amount", "toll_date",
]

# Map ticket types to their expected fields
TICKET_FIELDS_MAP: dict[TicketType, list[str]] = {
    TicketType.VAT_SPECIAL: VAT_SPECIAL_FIELDS,
    TicketType.VAT_NORMAL: VAT_NORMAL_FIELDS,
    TicketType.ELECTRONIC: ELECTRONIC_FIELDS,
    TicketType.TRAIN: TRAIN_FIELDS,
    TicketType.FLIGHT: FLIGHT_FIELDS,
    TicketType.TAXI: TAXI_FIELDS,
    TicketType.TOLL: TOLL_FIELDS,
}


# ── 字段标签映射（中文标签 ↔ 字段名，用于 format/parse 往返一致性）──

FIELD_LABELS: dict[str, str] = {
    # VAT / Electronic common
    "invoice_code": "发票代码",
    "invoice_number": "发票号码",
    "invoice_date": "开票日期",
    "buyer_name": "购方名称",
    "buyer_tax_id": "购方税号",
    "seller_name": "销方名称",
    "seller_tax_id": "销方税号",
    "amount": "金额",
    "tax_rate": "税率",
    "tax_amount": "税额",
    "total": "价税合计",
    # Train
    "departure_station": "出发站",
    "arrival_station": "到达站",
    "train_number": "车次",
    "seat_class": "座位等级",
    "ticket_price": "票价",
    # Flight
    "flight_number": "航班号",
    "departure": "出发地",
    "destination": "目的地",
    "fuel_surcharge": "燃油附加费",
    "civil_aviation_fund": "民航发展基金",
    # Taxi
    "pickup_time": "上车时间",
    "dropoff_time": "下车时间",
    "mileage": "里程",
    # Toll
    "toll_station": "收费站",
    "toll_date": "通行日期",
}

# Type-specific label overrides for fields that have different labels per ticket type
# Key: (ticket_type, field_name) → label
TYPE_FIELD_LABELS: dict[tuple[TicketType, str], str] = {
    # Train: passenger_name → 乘车人, travel_date → 乘车日期
    (TicketType.TRAIN, "passenger_name"): "乘车人",
    (TicketType.TRAIN, "travel_date"): "乘车日期",
    # Flight: passenger_name → 旅客姓名, travel_date → 乘机日期, total → 合计金额
    (TicketType.FLIGHT, "passenger_name"): "旅客姓名",
    (TicketType.FLIGHT, "travel_date"): "乘机日期",
    (TicketType.FLIGHT, "total"): "合计金额",
}


def get_field_label(ticket_type: TicketType, field_name: str) -> str:
    """Get the display label for a field, considering type-specific overrides."""
    key = (ticket_type, field_name)
    if key in TYPE_FIELD_LABELS:
        return TYPE_FIELD_LABELS[key]
    return FIELD_LABELS[field_name]


# Build reverse mapping including type-specific labels
LABEL_TO_FIELD: dict[str, str] = {v: k for k, v in FIELD_LABELS.items()}
for (_tt, fn), label in TYPE_FIELD_LABELS.items():
    LABEL_TO_FIELD[label] = fn

# Ticket type display names (Chinese)
TICKET_TYPE_LABELS: dict[TicketType, str] = {
    TicketType.VAT_SPECIAL: "增值税专用发票",
    TicketType.VAT_NORMAL: "增值税普通发票",
    TicketType.ELECTRONIC: "电子发票",
    TicketType.TRAIN: "火车票",
    TicketType.FLIGHT: "机票行程单",
    TicketType.TAXI: "出租车票",
    TicketType.TOLL: "过路费发票",
    TicketType.UNKNOWN: "未知类型",
}


# ── 票据类型检测 ──

def detect_ticket_type(ocr_text: str) -> TicketType:
    """
    根据 OCR 文本特征关键词判断票据类型。
    检测顺序有优先级：先检测更具体的类型，再检测更通用的类型。
    """
    if "增值税专用发票" in ocr_text:
        return TicketType.VAT_SPECIAL
    if "增值税普通发票" in ocr_text:
        return TicketType.VAT_NORMAL
    # 电子发票：包含"电子发票"但不包含"增值税"
    if "电子发票" in ocr_text and "增值税" not in ocr_text:
        return TicketType.ELECTRONIC
    if "火车票" in ocr_text or "铁路" in ocr_text or "车次" in ocr_text:
        return TicketType.TRAIN
    if "行程单" in ocr_text or "航班" in ocr_text or "机票" in ocr_text:
        return TicketType.FLIGHT
    if "出租" in ocr_text or "出租车" in ocr_text:
        return TicketType.TAXI
    if "过路费" in ocr_text or "通行费" in ocr_text:
        return TicketType.TOLL
    return TicketType.UNKNOWN


# ── 字段提取函数（每种票据类型独立的提取规则）──

def _extract_field(text: str, label: str) -> str:
    """
    通用字段提取：从文本中按 '标签：值' 或 '标签:值' 模式提取。
    支持中文冒号和英文冒号。
    """
    pattern = rf"{re.escape(label)}[：:]\s*(.+?)(?:\n|$)"
    match = re.search(pattern, text)
    if match:
        return match.group(1).strip()
    return ""


def _extract_vat_special_fields(text: str) -> dict:
    """提取增值税专用发票字段"""
    fields: dict = {}
    for field_name in VAT_SPECIAL_FIELDS:
        label = FIELD_LABELS[field_name]
        fields[field_name] = _extract_field(text, label)
    return fields


def _extract_vat_normal_fields(text: str) -> dict:
    """提取增值税普通发票字段"""
    fields: dict = {}
    for field_name in VAT_NORMAL_FIELDS:
        label = FIELD_LABELS[field_name]
        fields[field_name] = _extract_field(text, label)
    return fields


def _extract_electronic_fields(text: str) -> dict:
    """提取电子发票字段"""
    fields: dict = {}
    for field_name in ELECTRONIC_FIELDS:
        label = FIELD_LABELS[field_name]
        fields[field_name] = _extract_field(text, label)
    return fields


def _extract_train_fields(text: str) -> dict:
    """提取火车票字段"""
    fields: dict = {}
    for field_name in TRAIN_FIELDS:
        label = get_field_label(TicketType.TRAIN, field_name)
        fields[field_name] = _extract_field(text, label)
    return fields


def _extract_flight_fields(text: str) -> dict:
    """提取机票行程单字段"""
    fields: dict = {}
    for field_name in FLIGHT_FIELDS:
        label = get_field_label(TicketType.FLIGHT, field_name)
        fields[field_name] = _extract_field(text, label)
    return fields


def _extract_taxi_fields(text: str) -> dict:
    """提取出租车票字段"""
    fields: dict = {}
    for field_name in TAXI_FIELDS:
        label = FIELD_LABELS[field_name]
        fields[field_name] = _extract_field(text, label)
    return fields


def _extract_toll_fields(text: str) -> dict:
    """提取过路费发票字段"""
    fields: dict = {}
    for field_name in TOLL_FIELDS:
        label = FIELD_LABELS[field_name]
        fields[field_name] = _extract_field(text, label)
    return fields


# Extraction function dispatch
_EXTRACTORS: dict[TicketType, callable] = {
    TicketType.VAT_SPECIAL: _extract_vat_special_fields,
    TicketType.VAT_NORMAL: _extract_vat_normal_fields,
    TicketType.ELECTRONIC: _extract_electronic_fields,
    TicketType.TRAIN: _extract_train_fields,
    TicketType.FLIGHT: _extract_flight_fields,
    TicketType.TAXI: _extract_taxi_fields,
    TicketType.TOLL: _extract_toll_fields,
}


# ── 字段校验规则（每种票据类型独立的校验规则）──

def _validate_date_format(value: str, field_label: str) -> str | None:
    """校验日期格式 YYYY-MM-DD 或 YYYY/MM/DD 或 YYYYMMDD"""
    if not value:
        return f"{field_label}不能为空"
    if not re.match(r"^\d{4}[-/]?\d{2}[-/]?\d{2}$", value):
        return f"{field_label}格式不正确，期望 YYYY-MM-DD"
    return None


def _validate_invoice_code(value: str) -> str | None:
    """校验发票代码：10位或12位数字"""
    if not value:
        return "发票代码不能为空"
    if not re.match(r"^\d{10,12}$", value):
        return f"发票代码长度应为10-12位数字，实际: {value}"
    return None


def _validate_invoice_number(value: str) -> str | None:
    """校验发票号码：8位数字"""
    if not value:
        return "发票号码不能为空"
    if not re.match(r"^\d{8}$", value):
        return f"发票号码应为8位数字，实际: {value}"
    return None


def _validate_amount(value: str, field_label: str) -> str | None:
    """校验金额格式：数字，可带小数点"""
    if not value:
        return f"{field_label}不能为空"
    if not re.match(r"^-?\d+(\.\d{1,2})?$", value):
        return f"{field_label}格式不正确，期望数字: {value}"
    return None


def _validate_tax_id(value: str, field_label: str) -> str | None:
    """校验税号：15位、18位或20位"""
    if not value:
        return f"{field_label}不能为空"
    if not re.match(r"^[A-Za-z0-9]{15,20}$", value):
        return f"{field_label}长度应为15-20位，实际: {value}"
    return None


def _validate_train_number(value: str) -> str | None:
    """校验车次号：如 G1234, D5678, K123, T45, Z67 等"""
    if not value:
        return "车次不能为空"
    if not re.match(r"^[GDCZTK]\d{1,5}$", value):
        return f"车次格式不正确: {value}"
    return None


def _validate_flight_number(value: str) -> str | None:
    """校验航班号：如 CA1234, MU5678"""
    if not value:
        return "航班号不能为空"
    if not re.match(r"^[A-Z0-9]{2}\d{1,5}$", value):
        return f"航班号格式不正确: {value}"
    return None


def _validate_vat_special(fields: dict) -> list[str]:
    """增值税专用发票校验规则"""
    errors: list[str] = []
    err = _validate_invoice_code(fields.get("invoice_code", ""))
    if err:
        errors.append(err)
    err = _validate_invoice_number(fields.get("invoice_number", ""))
    if err:
        errors.append(err)
    err = _validate_date_format(fields.get("invoice_date", ""), "开票日期")
    if err:
        errors.append(err)
    err = _validate_tax_id(fields.get("buyer_tax_id", ""), "购方税号")
    if err:
        errors.append(err)
    err = _validate_tax_id(fields.get("seller_tax_id", ""), "销方税号")
    if err:
        errors.append(err)
    err = _validate_amount(fields.get("amount", ""), "金额")
    if err:
        errors.append(err)
    err = _validate_amount(fields.get("tax_amount", ""), "税额")
    if err:
        errors.append(err)
    err = _validate_amount(fields.get("total", ""), "价税合计")
    if err:
        errors.append(err)
    return errors


def _validate_vat_normal(fields: dict) -> list[str]:
    """增值税普通发票校验规则"""
    errors: list[str] = []
    err = _validate_invoice_code(fields.get("invoice_code", ""))
    if err:
        errors.append(err)
    err = _validate_invoice_number(fields.get("invoice_number", ""))
    if err:
        errors.append(err)
    err = _validate_date_format(fields.get("invoice_date", ""), "开票日期")
    if err:
        errors.append(err)
    err = _validate_amount(fields.get("amount", ""), "金额")
    if err:
        errors.append(err)
    err = _validate_amount(fields.get("total", ""), "价税合计")
    if err:
        errors.append(err)
    return errors


def _validate_electronic(fields: dict) -> list[str]:
    """电子发票校验规则"""
    errors: list[str] = []
    err = _validate_invoice_code(fields.get("invoice_code", ""))
    if err:
        errors.append(err)
    err = _validate_invoice_number(fields.get("invoice_number", ""))
    if err:
        errors.append(err)
    err = _validate_date_format(fields.get("invoice_date", ""), "开票日期")
    if err:
        errors.append(err)
    err = _validate_amount(fields.get("amount", ""), "金额")
    if err:
        errors.append(err)
    err = _validate_amount(fields.get("total", ""), "价税合计")
    if err:
        errors.append(err)
    return errors


def _validate_train(fields: dict) -> list[str]:
    """火车票校验规则"""
    errors: list[str] = []
    err = _validate_train_number(fields.get("train_number", ""))
    if err:
        errors.append(err)
    err = _validate_date_format(fields.get("travel_date", ""), "乘车日期")
    if err:
        errors.append(err)
    err = _validate_amount(fields.get("ticket_price", ""), "票价")
    if err:
        errors.append(err)
    return errors


def _validate_flight(fields: dict) -> list[str]:
    """机票行程单校验规则"""
    errors: list[str] = []
    err = _validate_flight_number(fields.get("flight_number", ""))
    if err:
        errors.append(err)
    err = _validate_date_format(fields.get("travel_date", ""), "乘机日期")
    if err:
        errors.append(err)
    err = _validate_amount(fields.get("ticket_price", ""), "票价")
    if err:
        errors.append(err)
    err = _validate_amount(fields.get("total", ""), "合计金额")
    if err:
        errors.append(err)
    return errors


def _validate_taxi(fields: dict) -> list[str]:
    """出租车票校验规则"""
    errors: list[str] = []
    err = _validate_amount(fields.get("amount", ""), "金额")
    if err:
        errors.append(err)
    return errors


def _validate_toll(fields: dict) -> list[str]:
    """过路费发票校验规则"""
    errors: list[str] = []
    err = _validate_amount(fields.get("amount", ""), "金额")
    if err:
        errors.append(err)
    err = _validate_date_format(fields.get("toll_date", ""), "通行日期")
    if err:
        errors.append(err)
    return errors


# Validation function dispatch
_VALIDATORS: dict[TicketType, callable] = {
    TicketType.VAT_SPECIAL: _validate_vat_special,
    TicketType.VAT_NORMAL: _validate_vat_normal,
    TicketType.ELECTRONIC: _validate_electronic,
    TicketType.TRAIN: _validate_train,
    TicketType.FLIGHT: _validate_flight,
    TicketType.TAXI: _validate_taxi,
    TicketType.TOLL: _validate_toll,
}


# ── TicketParser 主类 ──

class TicketParser:
    """
    多票据类型差异化解析器。

    支持票据类型：增值税专用发票、增值税普通发票、电子发票、
    火车票、机票行程单、出租车票、过路费发票。

    关键正确性属性：parse(format(ticket)) 往返一致性。
    """

    def parse(self, ocr_text: str) -> ParsedTicket:
        """
        解析 OCR 文本为结构化票据。

        1. 根据文本特征判断票据类型
        2. 按类型提取对应字段
        3. 执行字段校验规则
        4. 无法识别 → UNKNOWN + 原始文本
        """
        ticket_type = detect_ticket_type(ocr_text)

        if ticket_type == TicketType.UNKNOWN:
            return ParsedTicket(
                ticket_type=TicketType.UNKNOWN,
                fields={},
                raw_text=ocr_text,
                validation_errors=[],
            )

        # Extract fields using type-specific extractor
        extractor = _EXTRACTORS[ticket_type]
        fields = extractor(ocr_text)

        # Validate fields using type-specific validator
        validator = _VALIDATORS[ticket_type]
        validation_errors = validator(fields)

        return ParsedTicket(
            ticket_type=ticket_type,
            fields=fields,
            raw_text=ocr_text,
            validation_errors=validation_errors,
        )

    def format(self, ticket: ParsedTicket) -> str:
        """
        将结构化票据格式化为文本表示。

        输出格式设计为可被 parse 方法重新解析，保证往返一致性。
        格式：
            【票据类型名称】
            标签：值
            标签：值
            ...
        """
        if ticket.ticket_type == TicketType.UNKNOWN:
            return ticket.raw_text

        type_label = TICKET_TYPE_LABELS[ticket.ticket_type]
        field_names = TICKET_FIELDS_MAP.get(ticket.ticket_type, [])

        lines: list[str] = [f"【{type_label}】"]
        for field_name in field_names:
            label = get_field_label(ticket.ticket_type, field_name)
            value = ticket.fields.get(field_name, "")
            lines.append(f"{label}：{value}")

        return "\n".join(lines)
