"""
finance_agent.py
基于 Claude Agent SDK 的财务报销 Agent
- 用 @tool 注册三个工具：ocr_invoice / classify_account / generate_mcp_voucher
- 用 ClaudeSDKClient 管理多轮对话和工具调用
- 用 create_sdk_mcp_server 创建 in-process MCP 服务器
"""
import os
import re
import uuid
import json
import base64
import asyncio
import logging
import requests
from datetime import datetime
from dotenv import load_dotenv

from claude_agent_sdk import (
    tool,
    create_sdk_mcp_server,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    AssistantMessage,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
)

load_dotenv()
logger = logging.getLogger(__name__)

REMOTE_OCR_URL   = os.getenv("REMOTE_OCR_URL", "")
REMOTE_OCR_TOKEN = os.getenv("REMOTE_OCR_TOKEN", "")
ANTHROPIC_MODEL  = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")

# ── 全局会话存储（生产替换为 Redis）─────────────────────────────────
_sessions: dict[str, ClaudeSDKClient] = {}
_session_state: dict[str, dict] = {}   # 存储每个会话的上下文数据


# ════════════════════════════════════════════════════════════════════
# TOOL 1: ocr_invoice — 调用远程 PaddleOCR 识别发票
# ════════════════════════════════════════════════════════════════════
@tool(
    "ocr_invoice",
    "识别发票图片，提取票据类型、金额、税率、日期等结构化字段",
    {
        "image_base64": str,   # base64 编码的图片
        "filename":     str,   # 文件名，用于格式判断
    },
)
async def ocr_invoice(args: dict) -> dict:
    image_b64 = args.get("image_base64", "")
    filename  = args.get("filename", "invoice.png")

    if not image_b64:
        return {"error": "image_base64 不能为空"}

    # ── Step 1: 调用 PaddleOCR 远程服务 ────────────────────────────
    raw_text = ""
    try:
        img_bytes = base64.b64decode(image_b64)
        headers   = {}
        if REMOTE_OCR_TOKEN:
            headers["Authorization"] = f"Bearer {REMOTE_OCR_TOKEN}"

        resp = requests.post(
            REMOTE_OCR_URL,
            files={"file": (filename, img_bytes, "image/png")},
            headers=headers,
            timeout=60,
        )
        resp.raise_for_status()
        raw_text = resp.json().get("text", "")
        logger.info(f"OCR 识别完成，字符数: {len(raw_text)}")
    except Exception as e:
        logger.warning(f"远程 OCR 失败: {e}")
        return {"error": f"OCR 服务调用失败: {str(e)}", "raw_text": ""}

    # ── Step 2: 返回原始文本，由 Claude 自行提取结构化字段 ────────────
    return {
        "raw_text":    raw_text,
        "char_count":  len(raw_text),
        "ocr_success": True,
    }


# ════════════════════════════════════════════════════════════════════
# TOOL 2: classify_account — 本地规则匹配会计科目
# ════════════════════════════════════════════════════════════════════
ACCOUNT_RULES = [
    (["的士", "出租车", "打车", "滴滴", "网约车", "taxi"],  "6602.05", "交通费"),
    (["火车", "高铁", "动车", "飞机", "机票", "船票", "客运"], "6602.02", "差旅费"),
    (["住宿", "酒店", "宾馆", "民宿"],                      "6602.07", "住宿费"),
    (["餐", "饭", "食", "宴", "招待", "聚餐"],              "6602.01", "业务招待费"),
    (["办公", "文具", "耗材", "打印", "复印"],              "6602.03", "办公费"),
    (["电话", "通讯", "流量", "宽带", "话费"],              "6602.04", "通讯费"),
    (["培训", "课程", "学习", "会议"],                      "6602.08", "培训费"),
]

@tool(
    "classify_account",
    "根据票据类型和费用用途，匹配对应的会计科目代码和名称",
    {
        "ticket_type": str,  # 票据类型，如"的士票"
        "usage":       str,  # 费用用途描述
    },
)
async def classify_account(args: dict) -> dict:
    combined = f"{args.get('ticket_type','')} {args.get('usage','')}".lower()
    for keywords, code, name in ACCOUNT_RULES:
        if any(kw in combined for kw in keywords):
            logger.info(f"科目命中: {code} {name}")
            return {"account_code": code, "account_name": name, "matched": True}
    return {"account_code": "6602.99", "account_name": "其他费用", "matched": False}


# ════════════════════════════════════════════════════════════════════
# TOOL 3: generate_mcp_voucher — 生成 MCP 标准凭证报文
# ════════════════════════════════════════════════════════════════════
@tool(
    "generate_mcp_voucher",
    "将确认后的凭证草稿封装为 MCP 标准报文，提交 ERP 系统。仅在用户明确确认后调用。",
    {
        "summary":      str,    # 凭证摘要
        "department":   str,    # 部门
        "submitter":    str,    # 报销人
        "entries":      list,   # 借贷分录列表
        "total_amount": float,  # 总金额
        "invoice_info": dict,   # 发票信息
    },
)
async def generate_mcp_voucher(args: dict) -> dict:
    voucher_id = f"VOU-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    mcp = {
        "protocol":     "MCP/1.0",
        "voucher_type": "expense_reimbursement",
        "voucher_id":   voucher_id,
        "created_at":   datetime.now().isoformat(),
        "summary":      args.get("summary", ""),
        "department":   args.get("department", ""),
        "submitter":    args.get("submitter", ""),
        "entries":      args.get("entries", []),
        "total_amount": args.get("total_amount", 0),
        "source_invoice": args.get("invoice_info", {}),
        "status":       "pending_approval",
    }
    logger.info(f"MCP 凭证生成: {voucher_id}")
    return {"success": True, "voucher_id": voucher_id, "mcp_voucher": mcp}


# ════════════════════════════════════════════════════════════════════
# SYSTEM PROMPT
# ════════════════════════════════════════════════════════════════════
SYSTEM_PROMPT = """你是一个企业级财务报销智能助手，专门处理员工报销申请。

## 核心工作流（严格按顺序执行）
1. 从用户输入提取：部门(department)、报销人(submitter)、费用用途(usage)
2. 若用户上传了发票图片，调用 ocr_invoice 工具识别发票文字
3. 从 OCR 文本中提取：票据类型、发票号码、开票日期、总金额、税率、税额
4. 调用 classify_account 工具匹配会计科目
5. 计算价税分离：价款 = 总额 / (1 + 税率)，税额 = 总额 - 价款
6. 构建借贷分录，确保借贷平衡（借方合计 == 贷方合计）
7. 输出凭证数据（必须包含 VOUCHER_JSON 块，格式见下）
8. 收到用户明确确认（"确认"/"可以"/"OK"/"提交"）后，调用 generate_mcp_voucher 生成报文

## 借贷规则
- 借方：费用科目（如 6602.02 差旅费）+ 2221.01 应交税费-待抵扣进项税额（若有税率）
- 贷方：2241 其他应付款-[姓名]（金额 = 发票总额）
- 借贷必须平衡：借方合计 == 贷方合计

## 凭证输出格式（必须严格遵守）
生成凭证草稿时，必须在回复中包含以下 JSON 块，标记为 %%VOUCHER_JSON_START%% 和 %%VOUCHER_JSON_END%%：

%%VOUCHER_JSON_START%%
{
  "voucher_id": "VOU-YYYYMMDD-XXXXXX",
  "summary": "部门+姓名+报销用途",
  "department": "部门名称",
  "submitter": "报销人姓名",
  "usage": "费用用途",
  "entries": [
    {"account_code": "6602.02", "account_name": "差旅费-火车票", "debit": 394.04, "credit": 0},
    {"account_code": "2221.01", "account_name": "应交税费-待抵扣进项税额", "debit": 35.46, "credit": 0},
    {"account_code": "2241", "account_name": "其他应付款-张三", "debit": 0, "credit": 429.50}
  ],
  "total_debit": 429.50,
  "total_credit": 429.50,
  "balanced": true
}
%%VOUCHER_JSON_END%%

## 信息缺失处理
- 缺部门或姓名：礼貌追问，不生成凭证
- 缺金额：说明无法识别，请用户手动提供

## 约束
- 未经用户确认，严禁调用 generate_mcp_voucher
- 手机号中间4位用****替代
- 保持专业简洁的财务助手风格
- 每次生成或修改凭证后，必须输出完整的 VOUCHER_JSON 块
- 分录数量应根据实际票据和税费种类动态决定，不限于3条。多张票据需分别列示借方费用和税金
- 若一次上传多张票据，必须基于全部票据汇总金额，不可只按单张票据生成凭证"""


# ════════════════════════════════════════════════════════════════════
# Agent 工厂：为每个会话创建独立的 ClaudeSDKClient
# ════════════════════════════════════════════════════════════════════
def _create_agent(session_id: str) -> ClaudeSDKClient:
    """为会话创建带工具的 Agent 实例"""
    mcp_server = create_sdk_mcp_server(
        name="finance-tools",
        version="1.0.0",
        tools=[ocr_invoice, classify_account, generate_mcp_voucher],
    )
    options = ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        model=ANTHROPIC_MODEL,
        max_turns=20,
        mcp_servers=[mcp_server],
        allowed_tools=["ocr_invoice", "classify_account", "generate_mcp_voucher"],
    )
    client = ClaudeSDKClient(options=options)
    _sessions[session_id] = client
    _session_state[session_id] = {
        "last_voucher":  None,
        "last_mcp":      None,
        "pending_confirm": False,
    }
    return client


def _get_or_create_agent(session_id: str) -> ClaudeSDKClient:
    if session_id not in _sessions:
        return _create_agent(session_id)
    return _sessions[session_id]


# ════════════════════════════════════════════════════════════════════
# 主处理函数（供 FastAPI 调用）
# ════════════════════════════════════════════════════════════════════
async def process_message(
    session_id: str,
    message: str,
    image_base64: str | None = None,
    image_filename: str | None = None,
) -> dict:
    """
    处理一条用户消息，返回 {reply, action, voucher_html, mcp_voucher}
    """
    client = _get_or_create_agent(session_id)
    state  = _session_state[session_id]

    # ── 构建发送给 Agent 的提示 ───────────────────────────────────
    prompt_parts = []

    if image_base64:
        prompt_parts.append(
            f"[用户上传了发票图片: {image_filename or 'invoice.png'}]\n"
            f"图片base64已准备好，请调用 ocr_invoice 工具识别，"
            f"image_base64参数值为: {image_base64[:50]}...（已截断）\n"
            f"完整base64: {image_base64}\n"
            f"filename: {image_filename or 'invoice.png'}"
        )

    if message:
        prompt_parts.append(message)

    full_prompt = "\n\n".join(prompt_parts) if prompt_parts else message

    # ── 调用 Agent ────────────────────────────────────────────────
    reply_text   = ""
    voucher_html = None
    mcp_voucher  = None
    action       = "none"

    try:
        async with client.connect() as session:
            async for msg in session.send(full_prompt):
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            reply_text += block.text

                        elif isinstance(block, ToolResultBlock):
                            # 捕获工具返回结果
                            try:
                                result = json.loads(block.content) if isinstance(block.content, str) else block.content
                                if isinstance(result, list):
                                    for r in result:
                                        if isinstance(r, dict) and "text" in r:
                                            try:
                                                result = json.loads(r["text"])
                                            except Exception:
                                                pass
                                            break

                                if isinstance(result, dict):
                                    if result.get("mcp_voucher"):
                                        mcp_voucher = result["mcp_voucher"]
                                        state["last_mcp"] = mcp_voucher
                                        action = "posted"
                            except Exception as e:
                                logger.debug(f"解析工具结果失败: {e}")

    except Exception as e:
        logger.exception(f"Agent 处理失败: {e}")
        return {
            "reply":        f"处理失败：{str(e)}",
            "action":       "error",
            "voucher_html": None,
            "mcp_voucher":  None,
        }

    # ── 从回复中提取凭证 JSON 块 ──────────────────────────────────
    voucher_data = None
    json_match = re.search(
        r'%%VOUCHER_JSON_START%%\s*(.*?)\s*%%VOUCHER_JSON_END%%',
        reply_text, re.DOTALL
    )
    if json_match:
        try:
            voucher_data = json.loads(json_match.group(1))
            if action == "none":
                action = "preview"
                state["pending_confirm"] = True
            logger.info(f"凭证解析成功: {voucher_data.get('voucher_id','?')}，分录数: {len(voucher_data.get('entries',[]))}")
        except Exception as e:
            logger.warning(f"凭证 JSON 解析失败: {e}\n原始内容: {json_match.group(1)[:200]}")

    if mcp_voucher and action != "posted":
        action = "posted"

    return {
        "reply":        reply_text,
        "action":       action,
        "voucher_data": voucher_data,   # 结构化 JSON，前端直接用
        "voucher_html": None,           # 已废弃，保留兼容
        "mcp_voucher":  mcp_voucher,
    }


def clear_session(session_id: str):
    _sessions.pop(session_id, None)
    _session_state.pop(session_id, None)
