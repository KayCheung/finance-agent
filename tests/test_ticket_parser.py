"""
tests/test_ticket_parser.py
Ticket_Parser 的属性测试：票据解析往返一致性

Feature: finance-agent-architecture-upgrade, Property 21: 票据解析往返一致性
"""
import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from agent_core.models import TicketType, ParsedTicket
from tools.ticket_parser import TicketParser


# ── Hypothesis 自定义策略 ──

# 票据类型检测关键词，字段值中不能包含这些词以避免干扰类型检测
_TYPE_KEYWORDS = [
    "增值税专用发票", "增值税普通发票", "电子发票", "增值税",
    "火车票", "铁路", "车次",
    "行程单", "航班", "机票",
    "出租", "出租车",
    "过路费", "通行费",
]


def _no_type_keywords(s: str) -> bool:
    """确保字符串不包含任何票据类型检测关键词"""
    return all(kw not in s for kw in _TYPE_KEYWORDS)


# 安全文本策略：不含换行符和冒号（中英文），这些是 format 输出的分隔符
# 也排除 【】 以避免干扰票据类型检测
_safe_text = st.text(
    alphabet=st.characters(
        blacklist_categories=("Cs",),
        blacklist_characters="\n\r：:\x00【】",
    ),
    min_size=1,
    max_size=20,
).map(str.strip).filter(lambda s: len(s) > 0 and _no_type_keywords(s))

# 名称策略：中文名称，排除票据类型关键词
_chinese_name = st.text(
    alphabet=st.characters(
        whitelist_categories=("Lo",),  # CJK characters
    ),
    min_size=1,
    max_size=8,
).filter(lambda s: len(s) > 0 and _no_type_keywords(s))

# 日期策略：YYYY-MM-DD 格式
_date_strategy = st.dates(
    min_value=__import__("datetime").date(2000, 1, 1),
    max_value=__import__("datetime").date(2099, 12, 31),
).map(lambda d: d.strftime("%Y-%m-%d"))

# 金额策略：正数，最多两位小数
_amount_strategy = st.decimals(
    min_value=__import__("decimal").Decimal("0.01"),
    max_value=__import__("decimal").Decimal("999999.99"),
    allow_nan=False,
    allow_infinity=False,
    places=2,
).map(str)

# 发票代码：10-12位数字
_invoice_code = st.from_regex(r"\d{10,12}", fullmatch=True)

# 发票号码：8位数字
_invoice_number = st.from_regex(r"\d{8}", fullmatch=True)

# 税号：15-20位字母数字
_tax_id = st.from_regex(r"[A-Za-z0-9]{15,20}", fullmatch=True)

# 税率策略
_tax_rate = st.sampled_from(["0.03", "0.06", "0.09", "0.13"])

# 车次号：G/D/C/Z/T/K + 数字
_train_number = st.from_regex(r"[GDCZTK]\d{1,5}", fullmatch=True)

# 航班号：2个大写字母/数字 + 数字
_flight_number = st.from_regex(r"[A-Z]{2}\d{1,5}", fullmatch=True)

# 座位等级
_seat_class = st.sampled_from(["一等座", "二等座", "商务座", "硬座", "硬卧", "软卧"])

# 里程
_mileage = st.from_regex(r"\d{1,3}\.\d{1}", fullmatch=True)


# ── 各票据类型的 ParsedTicket 生成策略 ──

@st.composite
def vat_special_ticket(draw):
    """生成增值税专用发票 ParsedTicket"""
    fields = {
        "invoice_code": draw(_invoice_code),
        "invoice_number": draw(_invoice_number),
        "invoice_date": draw(_date_strategy),
        "buyer_name": draw(_chinese_name),
        "buyer_tax_id": draw(_tax_id),
        "seller_name": draw(_chinese_name),
        "seller_tax_id": draw(_tax_id),
        "amount": draw(_amount_strategy),
        "tax_rate": draw(_tax_rate),
        "tax_amount": draw(_amount_strategy),
        "total": draw(_amount_strategy),
    }
    return ParsedTicket(
        ticket_type=TicketType.VAT_SPECIAL,
        fields=fields,
        raw_text="",
        validation_errors=[],
    )


@st.composite
def train_ticket(draw):
    """生成火车票 ParsedTicket"""
    fields = {
        "passenger_name": draw(_chinese_name),
        "departure_station": draw(_chinese_name),
        "arrival_station": draw(_chinese_name),
        "train_number": draw(_train_number),
        "seat_class": draw(_seat_class),
        "ticket_price": draw(_amount_strategy),
        "travel_date": draw(_date_strategy),
    }
    return ParsedTicket(
        ticket_type=TicketType.TRAIN,
        fields=fields,
        raw_text="",
        validation_errors=[],
    )


@st.composite
def flight_ticket(draw):
    """生成机票行程单 ParsedTicket"""
    fields = {
        "passenger_name": draw(_chinese_name),
        "flight_number": draw(_flight_number),
        "departure": draw(_chinese_name),
        "destination": draw(_chinese_name),
        "ticket_price": draw(_amount_strategy),
        "fuel_surcharge": draw(_amount_strategy),
        "civil_aviation_fund": draw(_amount_strategy),
        "total": draw(_amount_strategy),
        "travel_date": draw(_date_strategy),
    }
    return ParsedTicket(
        ticket_type=TicketType.FLIGHT,
        fields=fields,
        raw_text="",
        validation_errors=[],
    )


@st.composite
def taxi_ticket(draw):
    """生成出租车票 ParsedTicket"""
    fields = {
        "pickup_time": draw(_date_strategy),
        "dropoff_time": draw(_date_strategy),
        "amount": draw(_amount_strategy),
        "mileage": draw(_mileage),
    }
    return ParsedTicket(
        ticket_type=TicketType.TAXI,
        fields=fields,
        raw_text="",
        validation_errors=[],
    )


@st.composite
def toll_ticket(draw):
    """生成过路费发票 ParsedTicket"""
    fields = {
        "toll_station": draw(_chinese_name),
        "amount": draw(_amount_strategy),
        "toll_date": draw(_date_strategy),
    }
    return ParsedTicket(
        ticket_type=TicketType.TOLL,
        fields=fields,
        raw_text="",
        validation_errors=[],
    )


# 所有已支持票据类型的联合策略
any_supported_ticket = st.one_of(
    vat_special_ticket(),
    train_ticket(),
    flight_ticket(),
    taxi_ticket(),
    toll_ticket(),
)


# ── Property 21: 票据解析往返一致性 ──
# Feature: finance-agent-architecture-upgrade, Property 21: 票据解析往返一致性


class TestProperty21TicketParseRoundTrip:
    """
    Property 21: 票据解析往返一致性

    For any 已支持票据类型的有效 ParsedTicket 对象，
    执行 parse(format(ticket)) 应产生与原始 ticket 等价的结构化对象。

    等价定义：ticket_type 相同，且 fields 中所有字段值相同。

    **Validates: Requirements 9.9**
    """

    parser = TicketParser()

    @given(ticket=any_supported_ticket)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_roundtrip_preserves_ticket_type_and_fields(self, ticket: ParsedTicket):
        """
        验证 parse(format(ticket)) 产生等价的结构化对象：
        - ticket_type 相同
        - fields 中所有字段值相同

        **Validates: Requirements 9.9**
        """
        formatted = self.parser.format(ticket)
        reparsed = self.parser.parse(formatted)

        # ticket_type 必须一致
        assert reparsed.ticket_type == ticket.ticket_type, (
            f"Ticket type mismatch: original={ticket.ticket_type}, "
            f"reparsed={reparsed.ticket_type}"
        )

        # 所有字段值必须一致
        for field_name, original_value in ticket.fields.items():
            reparsed_value = reparsed.fields.get(field_name, "")
            assert reparsed_value == original_value, (
                f"Field '{field_name}' mismatch for {ticket.ticket_type}: "
                f"original='{original_value}', reparsed='{reparsed_value}'"
            )

    @given(ticket=vat_special_ticket())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_roundtrip_vat_special(self, ticket: ParsedTicket):
        """
        增值税专用发票往返一致性。

        **Validates: Requirements 9.9**
        """
        formatted = self.parser.format(ticket)
        reparsed = self.parser.parse(formatted)

        assert reparsed.ticket_type == TicketType.VAT_SPECIAL
        for field_name in ticket.fields:
            assert reparsed.fields[field_name] == ticket.fields[field_name]

    @given(ticket=train_ticket())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_roundtrip_train(self, ticket: ParsedTicket):
        """
        火车票往返一致性。

        **Validates: Requirements 9.9**
        """
        formatted = self.parser.format(ticket)
        reparsed = self.parser.parse(formatted)

        assert reparsed.ticket_type == TicketType.TRAIN
        for field_name in ticket.fields:
            assert reparsed.fields[field_name] == ticket.fields[field_name]

    @given(ticket=flight_ticket())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_roundtrip_flight(self, ticket: ParsedTicket):
        """
        机票行程单往返一致性。

        **Validates: Requirements 9.9**
        """
        formatted = self.parser.format(ticket)
        reparsed = self.parser.parse(formatted)

        assert reparsed.ticket_type == TicketType.FLIGHT
        for field_name in ticket.fields:
            assert reparsed.fields[field_name] == ticket.fields[field_name]

    @given(ticket=taxi_ticket())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_roundtrip_taxi(self, ticket: ParsedTicket):
        """
        出租车票往返一致性。

        **Validates: Requirements 9.9**
        """
        formatted = self.parser.format(ticket)
        reparsed = self.parser.parse(formatted)

        assert reparsed.ticket_type == TicketType.TAXI
        for field_name in ticket.fields:
            assert reparsed.fields[field_name] == ticket.fields[field_name]

    @given(ticket=toll_ticket())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_roundtrip_toll(self, ticket: ParsedTicket):
        """
        过路费发票往返一致性。

        **Validates: Requirements 9.9**
        """
        formatted = self.parser.format(ticket)
        reparsed = self.parser.parse(formatted)

        assert reparsed.ticket_type == TicketType.TOLL
        for field_name in ticket.fields:
            assert reparsed.fields[field_name] == ticket.fields[field_name]


# ── 单元测试：各票据类型解析示例 ──
# 需求: 9.3, 9.4, 9.5, 9.6, 9.7


class TestVATSpecialInvoiceParsing:
    """
    增值税专用发票字段提取单元测试。

    **Validates: Requirements 9.3**
    """

    parser = TicketParser()

    def test_vat_special_full_fields(self):
        """测试增值税专用发票完整字段提取"""
        ocr_text = (
            "【增值税专用发票】\n"
            "发票代码：1234567890\n"
            "发票号码：12345678\n"
            "开票日期：2024-01-15\n"
            "购方名称：北京科技有限公司\n"
            "购方税号：91110108MA01ABCDEF\n"
            "销方名称：上海贸易有限公司\n"
            "销方税号：91310115MA01GHIJKL\n"
            "金额：10000.00\n"
            "税率：0.13\n"
            "税额：1300.00\n"
            "价税合计：11300.00"
        )
        result = self.parser.parse(ocr_text)

        assert result.ticket_type == TicketType.VAT_SPECIAL
        assert result.fields["invoice_code"] == "1234567890"
        assert result.fields["invoice_number"] == "12345678"
        assert result.fields["invoice_date"] == "2024-01-15"
        assert result.fields["buyer_name"] == "北京科技有限公司"
        assert result.fields["buyer_tax_id"] == "91110108MA01ABCDEF"
        assert result.fields["seller_name"] == "上海贸易有限公司"
        assert result.fields["seller_tax_id"] == "91310115MA01GHIJKL"
        assert result.fields["amount"] == "10000.00"
        assert result.fields["tax_rate"] == "0.13"
        assert result.fields["tax_amount"] == "1300.00"
        assert result.fields["total"] == "11300.00"
        assert result.validation_errors == []

    def test_vat_special_type_detection_from_raw_text(self):
        """测试从原始 OCR 文本中检测增值税专用发票类型"""
        ocr_text = (
            "增值税专用发票\n"
            "发票代码：3200221130\n"
            "发票号码：08765432\n"
            "开票日期：2024-06-20\n"
            "购方名称：测试公司\n"
            "购方税号：912345678901234AB\n"
            "销方名称：供应商公司\n"
            "销方税号：918765432109876CD\n"
            "金额：5000.00\n"
            "税率：0.06\n"
            "税额：300.00\n"
            "价税合计：5300.00"
        )
        result = self.parser.parse(ocr_text)
        assert result.ticket_type == TicketType.VAT_SPECIAL

    def test_vat_special_validation_errors(self):
        """测试增值税专用发票字段校验错误"""
        ocr_text = (
            "增值税专用发票\n"
            "发票代码：123\n"
            "发票号码：abc\n"
            "开票日期：not-a-date\n"
            "购方名称：测试\n"
            "购方税号：short\n"
            "销方名称：供应商\n"
            "销方税号：short2\n"
            "金额：abc\n"
            "税率：0.13\n"
            "税额：xyz\n"
            "价税合计：bad"
        )
        result = self.parser.parse(ocr_text)
        assert result.ticket_type == TicketType.VAT_SPECIAL
        assert len(result.validation_errors) > 0


class TestTrainTicketParsing:
    """
    火车票字段提取单元测试。

    **Validates: Requirements 9.4**
    """

    parser = TicketParser()

    def test_train_ticket_full_fields(self):
        """测试火车票完整字段提取"""
        ocr_text = (
            "【火车票】\n"
            "乘车人：张三\n"
            "出发站：北京南\n"
            "到达站：上海虹桥\n"
            "车次：G1234\n"
            "座位等级：二等座\n"
            "票价：553.00\n"
            "乘车日期：2024-03-15"
        )
        result = self.parser.parse(ocr_text)

        assert result.ticket_type == TicketType.TRAIN
        assert result.fields["passenger_name"] == "张三"
        assert result.fields["departure_station"] == "北京南"
        assert result.fields["arrival_station"] == "上海虹桥"
        assert result.fields["train_number"] == "G1234"
        assert result.fields["seat_class"] == "二等座"
        assert result.fields["ticket_price"] == "553.00"
        assert result.fields["travel_date"] == "2024-03-15"
        assert result.validation_errors == []

    def test_train_ticket_keyword_detection(self):
        """测试通过关键词'铁路'检测火车票类型"""
        ocr_text = (
            "中国铁路客票\n"
            "乘车人：李四\n"
            "出发站：广州南\n"
            "到达站：深圳北\n"
            "车次：D7890\n"
            "座位等级：一等座\n"
            "票价：100.00\n"
            "乘车日期：2024-05-01"
        )
        result = self.parser.parse(ocr_text)
        assert result.ticket_type == TicketType.TRAIN
        assert result.fields["passenger_name"] == "李四"
        assert result.fields["train_number"] == "D7890"


class TestFlightItineraryParsing:
    """
    机票行程单字段提取单元测试。

    **Validates: Requirements 9.5**
    """

    parser = TicketParser()

    def test_flight_itinerary_full_fields(self):
        """测试机票行程单完整字段提取"""
        ocr_text = (
            "【机票行程单】\n"
            "旅客姓名：王五\n"
            "航班号：CA1234\n"
            "出发地：北京\n"
            "目的地：成都\n"
            "票价：1200.00\n"
            "燃油附加费：50.00\n"
            "民航发展基金：60.00\n"
            "合计金额：1310.00\n"
            "乘机日期：2024-07-20"
        )
        result = self.parser.parse(ocr_text)

        assert result.ticket_type == TicketType.FLIGHT
        assert result.fields["passenger_name"] == "王五"
        assert result.fields["flight_number"] == "CA1234"
        assert result.fields["departure"] == "北京"
        assert result.fields["destination"] == "成都"
        assert result.fields["ticket_price"] == "1200.00"
        assert result.fields["fuel_surcharge"] == "50.00"
        assert result.fields["civil_aviation_fund"] == "60.00"
        assert result.fields["total"] == "1310.00"
        assert result.fields["travel_date"] == "2024-07-20"
        assert result.validation_errors == []

    def test_flight_keyword_detection_by_hangban(self):
        """测试通过关键词'航班'检测机票行程单类型"""
        ocr_text = (
            "航班信息\n"
            "旅客姓名：赵六\n"
            "航班号：MU5678\n"
            "出发地：上海\n"
            "目的地：广州\n"
            "票价：800.00\n"
            "燃油附加费：30.00\n"
            "民航发展基金：50.00\n"
            "合计金额：880.00\n"
            "乘机日期：2024-08-10"
        )
        result = self.parser.parse(ocr_text)
        assert result.ticket_type == TicketType.FLIGHT
        assert result.fields["flight_number"] == "MU5678"


class TestTaxiTicketParsing:
    """
    出租车票字段提取单元测试。

    **Validates: Requirements 9.6**
    """

    parser = TicketParser()

    def test_taxi_ticket_full_fields(self):
        """测试出租车票完整字段提取"""
        ocr_text = (
            "【出租车票】\n"
            "上车时间：2024-04-10\n"
            "下车时间：2024-04-10\n"
            "金额：35.00\n"
            "里程：12.5"
        )
        result = self.parser.parse(ocr_text)

        assert result.ticket_type == TicketType.TAXI
        assert result.fields["pickup_time"] == "2024-04-10"
        assert result.fields["dropoff_time"] == "2024-04-10"
        assert result.fields["amount"] == "35.00"
        assert result.fields["mileage"] == "12.5"
        assert result.validation_errors == []

    def test_taxi_keyword_detection(self):
        """测试通过关键词'出租'检测出租车票类型"""
        ocr_text = (
            "出租汽车发票\n"
            "上车时间：2024-09-01\n"
            "下车时间：2024-09-01\n"
            "金额：28.00\n"
            "里程：8.3"
        )
        result = self.parser.parse(ocr_text)
        assert result.ticket_type == TicketType.TAXI
        assert result.fields["amount"] == "28.00"


class TestUnknownTicketType:
    """
    未知票据类型处理单元测试。

    **Validates: Requirements 9.7**
    """

    parser = TicketParser()

    def test_unknown_type_returns_raw_text(self):
        """测试无法识别的票据类型返回 UNKNOWN 和原始文本"""
        ocr_text = "这是一段无法识别的文本内容，没有任何票据关键词"
        result = self.parser.parse(ocr_text)

        assert result.ticket_type == TicketType.UNKNOWN
        assert result.fields == {}
        assert result.raw_text == ocr_text
        assert result.validation_errors == []

    def test_unknown_type_with_empty_text(self):
        """测试空文本返回 UNKNOWN"""
        result = self.parser.parse("")
        assert result.ticket_type == TicketType.UNKNOWN
        assert result.fields == {}
        assert result.raw_text == ""

    def test_unknown_type_with_random_content(self):
        """测试随机内容返回 UNKNOWN"""
        ocr_text = "收据\n日期：2024-01-01\n金额：100元\n备注：办公用品"
        result = self.parser.parse(ocr_text)
        assert result.ticket_type == TicketType.UNKNOWN
