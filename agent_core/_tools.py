"""
agent_core/_tools.py
claude-agent-sdk @tool 定义，供 AgentCore 注册到 ClaudeSDKClient。

从老 finance_agent.py 迁移而来，保持相同的工具签名和行为。
"""
import base64
import logging
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from claude_agent_sdk import tool

logger = logging.getLogger(__name__)

# Module-level OCRService instance, injected by AgentCore.__init__
_ocr_service = None


def set_ocr_service(instance) -> None:
    """Set the module-level OCRService instance (called by AgentCore.__init__)."""
    global _ocr_service
    _ocr_service = instance


# ── TOOL 1: ocr_invoice ──

@tool(
    "ocr_invoice",
    "识别发票图片，提取票据类型、金额、税率、日期等结构化字段",
    {
        "image_base64": str,
        "filename": str,
    },
)
async def ocr_invoice(args: dict) -> dict:
    image_b64 = args.get("image_base64", "")
    filename = args.get("filename", "invoice.png")

    if not image_b64:
        return {"error": "image_base64 不能为空"}

    if _ocr_service is None:
        return {"error": "OCR 服务未初始化，请检查系统配置"}

    try:
        img_bytes = base64.b64decode(image_b64)
        result = await _ocr_service.recognize(img_bytes, filename)
        raw_text = result.raw_text
        logger.info("OCR 识别完成，模式: %s，字符数: %d", result.mode_used, len(raw_text))
    except Exception as e:
        logger.warning("OCR 识别失败: %s", e)
        return {"error": f"OCR 服务调用失败: {str(e)}", "raw_text": ""}

    return {
        "raw_text": raw_text,
        "char_count": len(raw_text),
        "ocr_success": True,
    }


# ── TOOL 2: classify_account ──

ACCOUNT_RULES = [
    (["的士", "出租车", "打车", "滴滴", "网约车", "taxi"], "6602.05", "交通费"),
    (["火车", "高铁", "动车", "飞机", "机票", "船票", "客运"], "6602.02", "差旅费"),
    (["住宿", "酒店", "宾馆", "民宿"], "6602.07", "住宿费"),
    (["餐", "饭", "食", "宴", "招待", "聚餐"], "6602.01", "业务招待费"),
    (["办公", "文具", "耗材", "打印", "复印"], "6602.03", "办公费"),
    (["电话", "通信", "流量", "宽带", "话费"], "6602.04", "通信费"),
    (["培训", "课程", "学习", "会议"], "6602.08", "培训费"),
]


@tool(
    "classify_account",
    "根据票据类型和费用用途，匹配对应的会计科目代码和名称",
    {
        "ticket_type": str,
        "usage": str,
    },
)
async def classify_account(args: dict) -> dict:
    combined = f"{args.get('ticket_type', '')} {args.get('usage', '')}".lower()
    for keywords, code, name in ACCOUNT_RULES:
        if any(kw in combined for kw in keywords):
            logger.info("科目命中: %s %s", code, name)
            return {"account_code": code, "account_name": name, "matched": True}
    return {"account_code": "6602.99", "account_name": "其他费用", "matched": False}


# ── TOOL 3: generate_mcp_voucher ──

@tool(
    "generate_mcp_voucher",
    "将确认后的凭证封装为 MCP 标准报文并提交。用户确认凭证后必须调用此工具。参数：summary(摘要), department(部门), submitter(报销人), amount(总金额数字), account_code(主科目代码), account_name(主科目名称), usage(费用用途)",
    {
        "summary": str,
        "department": str,
        "submitter": str,
        "amount": float,
        "account_code": str,
        "account_name": str,
        "usage": str,
    },
)
async def generate_mcp_voucher(args: dict) -> dict:
    voucher_id = f"VOU-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    mcp = {
        "protocol": "MCP/1.0",
        "voucher_type": "expense_reimbursement",
        "voucher_id": voucher_id,
        "created_at": datetime.now().isoformat(),
        "summary": args.get("summary", ""),
        "department": args.get("department", ""),
        "submitter": args.get("submitter", ""),
        "usage": args.get("usage", ""),
        "account_code": args.get("account_code", ""),
        "account_name": args.get("account_name", ""),
        "amount": args.get("amount", 0),
        "status": "pending_approval",
    }
    import json
    logger.info("══════ MCP 凭证报文 ══════")
    logger.info(json.dumps(mcp, ensure_ascii=False, indent=2))
    logger.info("══════ MCP 报文结束 ══════")
    return {"success": True, "voucher_id": voucher_id, "mcp_voucher": mcp}


# ── TOOL 4: tax_calculate ──

@tool(
    "tax_calculate",
    "确定性价税分离计算，使用 Decimal 精确计算避免浮点误差",
    {
        "total_amount": str,
        "tax_rate": str,
    },
)
async def tax_calculate(args: dict) -> dict:
    from tools.tax_calculator import calculate_tax

    total_amount_str = args.get("total_amount", "")
    tax_rate_str = args.get("tax_rate", None)

    if not total_amount_str:
        return {"error": "total_amount 不能为空"}

    try:
        total_amount = Decimal(str(total_amount_str))
        tax_rate = Decimal(str(tax_rate_str)) if tax_rate_str else None
    except Exception as e:
        return {"error": f"参数格式错误: {str(e)}"}

    try:
        result = calculate_tax(total_amount, tax_rate)
        return {
            "total_amount": str(result.total_amount),
            "tax_rate": str(result.tax_rate),
            "amount_without_tax": str(result.amount_without_tax),
            "tax_amount": str(result.tax_amount),
            "balanced": result.balanced,
        }
    except ValueError as e:
        return {"error": str(e)}


def get_sdk_tools() -> list:
    """返回所有 @tool 装饰的工具函数列表。"""
    return [ocr_invoice, classify_account, generate_mcp_voucher, tax_calculate]
