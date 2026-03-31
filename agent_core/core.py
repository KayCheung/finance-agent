"""
agent_core/core.py
Agent_Core：核心能力层，与 HTTP 网关和前端解耦。

支持两种运行模式：
- STANDALONE：自带 HTTP 网关和前端（当前形态）
- EMBEDDED：作为子 Agent 被上层 Orchestrator Agent 调用，无 HTTP 层

提供统一的 invoke() 入口、能力声明、MCP 工具注册和事件回调接口。
"""
import base64
import json
import logging
import os
import re
import time
from decimal import Decimal, ROUND_HALF_UP
from typing import Callable, Optional

from dotenv import load_dotenv

from claude_agent_sdk import (
    tool,
    create_sdk_mcp_server,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    AssistantMessage,
    TextBlock,
    ToolResultBlock,
)
from claude_agent_sdk.types import ResultMessage

from agent_core.config import AgentConfig, OCRConfig
from agent_core.models import (
    AgentAction,
    AgentMode,
    AgentRequest,
    AgentResponse,
    CapabilityDeclaration,
    UserIdentity,
)
from tools.ocr_service import OCRService, OCRUnavailableError
from tools.ocr_service import OCRConfig as OCRServiceConfig

load_dotenv()
logger = logging.getLogger(__name__)

ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")

# System prompt — 与老 finance_agent.py 保持一致
_SYSTEM_PROMPT = """你是一个企业级财务报销智能助手，专门处理员工报销申请。

## 核心工作流（严格按顺序执行）
1. 从用户输入提取：部门(department)、报销人(submitter)、费用用途(usage)
2. 若用户上传了发票图片，OCR 识别已在预处理阶段完成，识别结果已包含在用户消息中（标记为"以下是 OCR 识别结果"），无需再调用 ocr_invoice 工具
3. 从 OCR 文本中提取：票据类型、发票号码、开票日期、总金额、税率、税额
4. 调用 classify_account 工具匹配会计科目
5. 计算价税分离：价款 = 总额 / (1 + 税率)，税额 = 总额 - 价款
6. 构建借贷分录，确保借贷平衡（借方合计 == 贷方合计）
7. 输出凭证数据（必须包含 VOUCHER_JSON 块，格式见下）
8. 收到用户明确确认（"确认"/"可以"/"OK"/"提交"）后，立即调用 generate_mcp_voucher 工具生成报文，不要重复展示凭证信息

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

## 确认后行为（极其重要）
- 收到用户确认消息后，必须立即调用 generate_mcp_voucher 工具
- 调用时使用用户确认的凭证信息作为参数（summary, department, submitter, amount, account_code, account_name, usage）
- 调用后只需简短回复"凭证已提交"，不要重复展示凭证明细
- 严禁在确认后重新询问部门、姓名等已提供的信息

## 约束
- 未经用户确认，严禁调用 generate_mcp_voucher
- 保持专业简洁的财务助手风格
- 每次生成或修改凭证后，必须输出完整的 VOUCHER_JSON 块
- 分录数量应根据实际票据和税费种类动态决定，不限于3条。多张票据需分别列示借方费用和税金
- 若一次上传多张票据，必须基于全部票据汇总金额，不可只按单张票据生成凭证

## 支持的票据类型
增值税专用发票、增值税普通发票、电子发票、火车票、机票行程单、出租车票、过路费发票
"""

logger = logging.getLogger(__name__)


def _parse_amount_candidates(text: str) -> list[Decimal]:
    if not text:
        return []
    normalized = text.replace(",", "").replace("，", "")
    decimal_candidates: list[Decimal] = []
    integer_candidates: list[Decimal] = []
    
    for m in re.finditer(r"(?<!\d)(\d{1,9}(?:\.\d{1,2})?)(?!\d)", normalized):
        try:
            val_str = m.group(1)
            v = Decimal(val_str)
        except Exception:
            continue
            
        if v <= 0 or v > Decimal("100000000"):
            continue
            
        if "." in val_str:
            decimal_candidates.append(v)
        else:
            # For integers, heavily penalize > 1000 to avoid years (e.g. 2018) and train numbers (e.g. 8166)
            if v <= 1000:
                integer_candidates.append(v)
                
    if decimal_candidates:
        return decimal_candidates
    return integer_candidates


def _extract_total_amount_from_ocr(text: str) -> Optional[Decimal]:
    if not text:
        return None
    normalized = text.replace(",", "").replace("，", "")
    keyword_patterns = [
        r"(?:价税合计|合计金额|总金额|票价|金额|实收金额|应付金额)\D{0,12}(\d{1,9}(?:\.\d{1,2})?)",
        r"(?:¥|￥)\s*(\d{1,9}(?:\.\d{1,2})?)",
    ]
    for pat in keyword_patterns:
        for m in re.finditer(pat, normalized, re.IGNORECASE):
            try:
                val_str = m.group(1)
                v = Decimal(val_str)
                if v > 0:
                    # Avoid picking up dates (e.g. 20240315) or large IDs as fallback amounts
                    if "." not in val_str and v >= 10000:
                        continue
                    return v
            except Exception:
                pass

    candidates = _parse_amount_candidates(normalized)
    if not candidates:
        return None
    return max(candidates)


def _round2(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _decimal_from_any(v: object, default: Decimal = Decimal("0")) -> Decimal:
    try:
        return Decimal(str(v))
    except Exception:
        return default


_TICKET_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "taxi": ("的士", "出租车", "打车"),
    "bus": ("客运汽车", "汽车票", "大巴"),
    "air": ("机票", "航班", "行程单"),
    "rail": ("火车票", "高铁", "动车", "铁路"),
}


def _guess_ticket_category(text: str) -> Optional[str]:
    s = str(text or "")
    for cat, kws in _TICKET_CATEGORY_KEYWORDS.items():
        if any(kw in s for kw in kws):
            return cat
    return None


def _extract_ticket_amount_overrides(text: str) -> dict[str, Decimal]:
    s = str(text or "")
    if not s:
        return {}
    compact = re.sub(r"\s+", "", s)
    overrides: dict[str, Decimal] = {}
    for cat, kws in _TICKET_CATEGORY_KEYWORDS.items():
        key_pat = "|".join(re.escape(x) for x in kws)
        patterns = [
            rf"(?:{key_pat})\D{{0,10}}(?:金额|票价|价税合计|合计)?(?:为|是)?\D{{0,4}}(\d{{1,9}}(?:\.\d{{1,2}})?)",
            rf"(?:{key_pat})\D{{0,6}}(\d{{1,9}}(?:\.\d{{1,2}})?)元",
        ]
        for pat in patterns:
            m = re.search(pat, compact, re.IGNORECASE)
            if not m:
                continue
            try:
                amount = Decimal(m.group(1))
                if amount > 0:
                    overrides[cat] = _round2(amount)
                    break
            except Exception:
                continue
    return overrides


def _resolve_amount_total_from_cache(cache: dict) -> Optional[Decimal]:
    if not isinstance(cache, dict):
        return None
    items = cache.get("items")
    overrides = cache.get("overrides") or {}
    if not isinstance(items, list) or not items:
        return None

    total = Decimal("0")
    found = False
    for item in items:
        if not isinstance(item, dict):
            continue
        base = item.get("amount")
        category = str(item.get("category") or "")
        amount = _decimal_from_any(base, Decimal("-1"))
        if category and category in overrides:
            amount = _decimal_from_any(overrides.get(category), amount)
        if amount > 0:
            total += amount
            found = True
    if not found:
        return None
    return _round2(total)


def _voucher_total_debit(voucher: dict) -> Decimal:
    td = voucher.get("total_debit")
    if td is not None:
        return _decimal_from_any(td, Decimal("0"))
    entries = voucher.get("entries") or []
    total = Decimal("0")
    for e in entries:
        if isinstance(e, dict):
            total += _decimal_from_any(e.get("debit"), Decimal("0"))
    return total


def _force_voucher_total(voucher: dict, target_total: Decimal, submitter: str = "") -> dict:
    entries = [dict(x) for x in (voucher.get("entries") or []) if isinstance(x, dict)]
    if not entries:
        entries = [
            {"account_code": "6602.02", "account_name": "差旅费", "debit": 0, "credit": 0},
            {"account_code": "2241", "account_name": f"其他应付款-{submitter}" if submitter else "其他应付款", "debit": 0, "credit": 0},
        ]

    debit_indices = [i for i, e in enumerate(entries) if _decimal_from_any(e.get("debit")) > 0]
    if not debit_indices:
        debit_indices = [0]
        entries[0]["debit"] = "0"

    old_debit_sum = sum((_decimal_from_any(entries[i].get("debit")) for i in debit_indices), Decimal("0"))
    remaining = target_total
    for idx in debit_indices[:-1]:
        base = _decimal_from_any(entries[idx].get("debit"))
        scaled = _round2(target_total * (base / old_debit_sum)) if old_debit_sum > 0 else Decimal("0")
        entries[idx]["debit"] = str(scaled)
        entries[idx]["credit"] = "0"
        remaining -= scaled
    last_idx = debit_indices[-1]
    last_debit = _round2(remaining)
    entries[last_idx]["debit"] = str(last_debit)
    entries[last_idx]["credit"] = "0"

    credit_indices = [i for i, e in enumerate(entries) if _decimal_from_any(e.get("credit")) > 0]
    if not credit_indices:
        credit_indices = [len(entries) - 1]
    for idx in credit_indices:
        entries[idx]["debit"] = "0"
        entries[idx]["credit"] = "0"
    entries[credit_indices[0]]["credit"] = str(_round2(target_total))

    voucher["entries"] = entries
    voucher["total_debit"] = str(_round2(target_total))
    voucher["total_credit"] = str(_round2(target_total))
    voucher["balanced"] = True
    return voucher


def _apply_known_profile_to_voucher(voucher: dict, known_profile: dict) -> dict:
    if not isinstance(voucher, dict) or not isinstance(known_profile, dict):
        return voucher
    department = str(known_profile.get("department") or "").strip()
    submitter = str(known_profile.get("submitter") or "").strip()
    usage = str(known_profile.get("usage") or "").strip()

    if department:
        voucher["department"] = department
    if submitter:
        voucher["submitter"] = submitter
    if usage:
        voucher["usage"] = usage

    if department or submitter or usage:
        voucher["summary"] = f"{department}{submitter}{usage}".strip()

    entries = voucher.get("entries") or []
    if isinstance(entries, list) and submitter:
        for e in entries:
            if not isinstance(e, dict):
                continue
            code = str(e.get("account_code") or "")
            name = str(e.get("account_name") or "")
            if code.startswith("2241") or "其他应付款" in name:
                e["account_name"] = f"其他应付款-{submitter}"
                break
    return voucher


# MCP tool definitions for embedded mode registration
_MCP_TOOL_DEFINITIONS = [
    {
        "name": "ocr_invoice",
        "description": "发票图片 OCR 识别，返回结构化文本",
        "input_schema": {
            "type": "object",
            "properties": {
                "image_base64": {"type": "string", "description": "Base64 编码的发票图片"},
                "filename": {"type": "string", "description": "文件名"},
            },
            "required": ["image_base64"],
        },
    },
    {
        "name": "classify_account",
        "description": "会计科目智能匹配，支持 RAG/LLM/关键词三策略降级",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticket_type": {"type": "string", "description": "票据类型"},
                "usage": {"type": "string", "description": "费用用途描述"},
            },
            "required": ["ticket_type", "usage"],
        },
    },
    {
        "name": "generate_mcp_voucher",
        "description": "生成 MCP 标准凭证报文",
        "input_schema": {
            "type": "object",
            "properties": {
                "department": {"type": "string"},
                "submitter": {"type": "string"},
                "usage": {"type": "string"},
                "account_code": {"type": "string"},
                "account_name": {"type": "string"},
                "amount": {"type": "number"},
                "summary": {"type": "string"},
            },
            "required": ["department", "submitter", "usage", "account_code", "account_name", "amount", "summary"],
        },
    },
    {
        "name": "tax_calculate",
        "description": "确定性价税分离计算",
        "input_schema": {
            "type": "object",
            "properties": {
                "total_amount": {"type": "string", "description": "含税总额（Decimal 字符串）"},
                "tax_rate": {"type": "string", "description": "税率（Decimal 字符串）"},
            },
            "required": ["total_amount"],
        },
    },
]


class AgentCore:
    """
    Finance Agent 核心能力层。

    与 HTTP 网关和前端完全解耦，可作为独立子 Agent
    被企业级 Orchestrator Agent 调用。
    """

    def __init__(self, mode: AgentMode, config: AgentConfig, ocr_config: Optional[OCRConfig] = None) -> None:
        self._mode = mode
        self._config = config

        # Initialize OCRService from OCRConfig
        _ocr_cfg = ocr_config or OCRConfig()
        self._ocr_service = OCRService(
            OCRServiceConfig(
                preferred_mode=_ocr_cfg.preferred_mode,
                cloud_url=_ocr_cfg.cloud_url,
                cloud_timeout=_ocr_cfg.cloud_timeout,
                local_timeout=_ocr_cfg.local_timeout,
                retry_count=_ocr_cfg.retry_count,
                local_lang=_ocr_cfg.local_lang,
                local_use_angle_cls=_ocr_cfg.local_use_angle_cls,
                local_use_gpu=_ocr_cfg.local_use_gpu,
                local_model_dir=_ocr_cfg.local_model_dir,
            )
        )

        # Inject OCRService into _tools module
        from agent_core import _tools
        _tools.set_ocr_service(self._ocr_service)

        # Internal session management (standalone mode)
        self._internal_sessions: dict[str, dict] = {}

        # Per-session ClaudeSDKClient instances
        self._sdk_clients: dict[str, ClaudeSDKClient] = {}

        # Per-session OCR result cache for multi-turn context
        # Structure: {session_id: [{"filename": str, "raw_text": str}, ...]}
        self._session_ocr_cache: dict[str, list[dict[str, str]]] = {}
        # Per-session amount hints for multi-image aggregation and manual overrides
        # Structure: {session_id: {"items": [{"filename","category","amount"}], "overrides": {cat: amount}}}
        self._session_amount_cache: dict[str, dict] = {}
        # Per-session user message cache for context continuity
        self._session_context_cache: dict[str, list[str]] = {}

        # Event callbacks for Orchestrator integration
        self.on_voucher_created: Optional[Callable] = None
        self.on_voucher_confirmed: Optional[Callable] = None
        self.on_voucher_submitted: Optional[Callable] = None

        logger.info("AgentCore initialized in %s mode", mode.value)

    @property
    def mode(self) -> AgentMode:
        return self._mode

    @mode.setter
    def mode(self, value: AgentMode) -> None:
        logger.info("AgentCore mode switching from %s to %s", self._mode.value, value.value)
        self._mode = value

    async def invoke(self, request: AgentRequest) -> AgentResponse:
        """
        统一入口，接收结构化请求，返回结构化结果。

        嵌入模式下使用外部传入的 session_context 和 user_identity。
        独立模式下使用内部会话管理。
        """
        try:
            # Resolve context based on mode
            session_context, user_identity = self._resolve_context(request)

            # Process the request intent
            response = await self._process_request(request, session_context, user_identity)

            return response

        except Exception as e:
            logger.error("AgentCore invoke error: %s", str(e))
            return AgentResponse(
                success=False,
                reply=f"处理请求时发生错误: {str(e)}",
                action=AgentAction.ERROR,
                errors=[str(e)],
            )

    def _resolve_context(
        self, request: AgentRequest
    ) -> tuple[dict, Optional[UserIdentity]]:
        """
        Resolve session context and user identity based on mode.

        Embedded mode: use external context from request.
        Standalone mode: use internal session management.
        """
        if self._mode == AgentMode.EMBEDDED:
            # Embedded mode: use externally provided context
            session_context = request.session_context or {}
            user_identity = request.user_identity
            logger.debug(
                "Embedded mode: using external context, user=%s",
                user_identity.user_id if user_identity else "unknown",
            )
            return session_context, user_identity

        # Standalone mode: internal session management
        session_id = request.session_id or "default"
        if session_id not in self._internal_sessions:
            self._internal_sessions[session_id] = {
                "session_id": session_id,
                "messages": [],
            }
        session_context = self._internal_sessions[session_id]
        user_identity = request.user_identity
        return session_context, user_identity

    async def _process_request(
        self,
        request: AgentRequest,
        session_context: dict,
        user_identity: Optional[UserIdentity],
    ) -> AgentResponse:
        """
        Process the request using claude-agent-sdk's ClaudeSDKClient.
        Maintains per-session Agent instances for multi-turn dialogue.
        """
        message = request.message or ""
        if not message and not request.images:
            return AgentResponse(
                success=True,
                reply="请输入您的问题或上传发票图片。",
                action=AgentAction.NONE,
            )

        session_id = request.session_id or "default"

        # Build prompt: use OCR for images instead of raw base64
        prompt_parts = []
        external_context = request.session_context or {}
        known_profile = external_context.get("known_profile") if isinstance(external_context, dict) else None
        known_amount = external_context.get("known_amount") if isinstance(external_context, dict) else None
        history_messages = external_context.get("history_messages") if isinstance(external_context, dict) else None

        if isinstance(known_profile, dict):
            profile_lines = []
            if known_profile.get("department"):
                profile_lines.append(f"部门: {known_profile['department']}")
            if known_profile.get("submitter"):
                profile_lines.append(f"报销人: {known_profile['submitter']}")
            if known_profile.get("usage"):
                profile_lines.append(f"用途: {known_profile['usage']}")
            if profile_lines:
                prompt_parts.append(
                    "以下为本会话用户已提供信息（无需重复询问，除非用户主动更改）：\n"
                    + "\n".join(profile_lines)
                )

        if isinstance(history_messages, list) and history_messages:
            normalized = []
            for item in history_messages[-8:]:
                if not isinstance(item, dict):
                    continue
                role = str(item.get("role") or "").strip()
                content = str(item.get("content") or "").strip()
                if role in {"user", "assistant"} and content:
                    normalized.append(f"{role}: {content}")
            if normalized:
                prompt_parts.append(
                    "最近会话摘要（请保持上下文连续，不要重复收集已确认字段）：\n"
                    + "\n".join(normalized)
                )
        expected_total_amount: Optional[Decimal] = None
        expected_total_source = ""
        if isinstance(known_amount, dict):
            total_text = str(known_amount.get("total_amount") or "").strip()
            line_amounts = known_amount.get("line_amounts")
            if total_text:
                try:
                    expected_total_amount = Decimal(total_text)
                    expected_total_source = "manual"
                except Exception:
                    expected_total_amount = None
            if expected_total_amount is not None:
                lines_hint = ""
                if isinstance(line_amounts, list) and line_amounts:
                    lines_hint = f"\n用户提供的逐项金额: {', '.join(str(x) for x in line_amounts)}"
                prompt_parts.append(
                    "用户已人工确认金额信息：\n"
                    f"总金额={_round2(expected_total_amount)}。生成凭证时 total_debit/total_credit 必须等于该总金额。"
                    + lines_hint
                    + "\n若与你的识别结果冲突，以用户人工确认金额为准。"
                )

        if request.images:
            per_image_amounts: list[tuple[str, Optional[Decimal]]] = []
            current_ocr_payloads: list[dict[str, str]] = []
            for img in request.images:
                image_b64 = img.get("image_base64", "")
                filename = img.get("filename", "invoice.png")
                if image_b64:
                    try:
                        image_bytes = base64.b64decode(image_b64)
                        ocr_start = time.monotonic()
                        ocr_result = await self._ocr_service.recognize(image_bytes, filename)
                        ocr_elapsed = int((time.monotonic() - ocr_start) * 1000)
                        logger.info(
                            "OCR 完成 [文件=%s, 模式=%s, 耗时=%dms, 字符数=%d]",
                            filename,
                            ocr_result.mode_used,
                            ocr_elapsed,
                            ocr_result.char_count,
                        )
                        prompt_parts.append(f"以下是 OCR 识别结果（文件: {filename}）：\n{ocr_result.raw_text}")
                        current_ocr_payloads.append({"filename": filename, "raw_text": ocr_result.raw_text})
                        per_image_amounts.append((filename, _extract_total_amount_from_ocr(ocr_result.raw_text)))
                    except OCRUnavailableError:
                        logger.error("OCR 服务不可用，无法处理图片: %s", filename)
                        return AgentResponse(
                            success=False,
                            reply="OCR 服务暂时不可用，请稍后重试或联系管理员。",
                            action=AgentAction.ERROR,
                            errors=["OCR 服务不可用"],
                        )
            if current_ocr_payloads:
                # 缓存本轮全部 OCR 结果，供后续纯文本轮次引用
                self._session_ocr_cache[session_id] = current_ocr_payloads
                # 记录本轮票据金额信息，支持后续补充“某张票金额为 X 元”后重算汇总
                self._session_amount_cache[session_id] = {
                    "items": [
                        {
                            "filename": fname,
                            "category": _guess_ticket_category(fname) or "",
                            "amount": amt,
                        }
                        for fname, amt in per_image_amounts
                    ],
                    "overrides": {},
                }
            if len(request.images) > 1:
                known_amounts = [x[1] for x in per_image_amounts if x[1] is not None]
                summary_lines = [
                    f"- {fname}: {amt if amt is not None else '未识别金额'}"
                    for fname, amt in per_image_amounts
                ]
                total_hint = (
                    f"{sum(known_amounts, Decimal('0')).quantize(Decimal('0.01'))}"
                    if known_amounts
                    else "未识别"
                )
                prompt_parts.insert(
                    0,
                    "系统多票据汇总信息：\n"
                    f"本次共上传 {len(request.images)} 张票据，请基于全部票据生成凭证，不可只用单张。\n"
                    + "\n".join(summary_lines)
                    + f"\n汇总金额参考: {total_hint}\n"
                    "若单张金额识别不完整，请结合 OCR 原文修正；最终 total_debit/total_credit 必须与全部票据汇总一致。",
                )
        if message:
            prompt_parts.append(message)
            # 缓存用户消息中的关键信息（部门、姓名、用途）
            if session_id not in self._session_context_cache:
                self._session_context_cache[session_id] = []
            self._session_context_cache[session_id].append(message)
            # 抽取用户人工纠正金额（如“的士票金额为10元”）并写入会话覆盖
            overrides = _extract_ticket_amount_overrides(message)
            if overrides:
                bucket = self._session_amount_cache.setdefault(session_id, {"items": [], "overrides": {}})
                existing = bucket.get("overrides")
                if not isinstance(existing, dict):
                    existing = {}
                for k, v in overrides.items():
                    existing[k] = _round2(v)
                bucket["overrides"] = existing

        # 无用户显式总额时，回退到多票据汇总（含人工票种金额覆盖）
        if expected_total_amount is None:
            cached_total = _resolve_amount_total_from_cache(self._session_amount_cache.get(session_id, {}))
            if cached_total is not None:
                expected_total_amount = cached_total
                expected_total_source = "multi_ticket"
                prompt_parts.append(
                    "系统汇总金额约束：\n"
                    f"当前会话多票据汇总总额={_round2(expected_total_amount)}。"
                    "生成凭证时 total_debit/total_credit 必须与该总额一致。"
                )

        # 如果本次没有图片但会话中有缓存的 OCR 结果，注入上下文
        if not request.images and session_id in self._session_ocr_cache:
            cached_payloads = self._session_ocr_cache.get(session_id, [])
            cached_ocr = "\n\n".join(
                f"[文件: {p.get('filename', 'unknown')}]\n{p.get('raw_text', '')}"
                for p in cached_payloads
                if isinstance(p, dict)
            )
            # 拼接之前的对话上下文
            prev_context = ""
            if session_id in self._session_context_cache:
                prev_msgs = self._session_context_cache[session_id][:-1]  # 排除当前消息
                if prev_msgs:
                    prev_context = "\n用户之前提供的信息：\n" + "\n".join(prev_msgs[-5:])  # 最近5条
            if cached_ocr.strip():
                prompt_parts.insert(0, f"（之前上传的发票 OCR 识别结果如下，请基于此信息继续处理，不要重复询问已提供的信息）\n{cached_ocr}{prev_context}")

        full_prompt = "\n\n".join(prompt_parts) if prompt_parts else message

        # Get or create per-session ClaudeSDKClient
        client = self._get_or_create_sdk_client(session_id)

        # Call Agent
        reply_text = ""
        mcp_voucher = None
        voucher_data = None
        action = AgentAction.NONE

        try:
            await client.connect()
            await client.query(full_prompt, session_id=session_id)
            async for msg in client.receive_messages():
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            reply_text += block.text
                        elif isinstance(block, ToolResultBlock):
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
                                if isinstance(result, dict) and result.get("mcp_voucher"):
                                    mcp_voucher = result["mcp_voucher"]
                                    action = AgentAction.POSTED
                            except Exception as e:
                                logger.debug("解析工具结果失败: %s", e)
                elif isinstance(msg, ResultMessage):
                    # End of conversation turn
                    break
        except Exception as e:
            logger.exception("Agent SDK 调用失败: %s", e)
            return AgentResponse(
                success=False,
                reply=f"AI 服务调用失败: {str(e)}",
                action=AgentAction.ERROR,
                errors=[str(e)],
            )

        # Extract voucher JSON from reply text
        json_match = re.search(
            r'%%VOUCHER_JSON_START%%\s*(.*?)\s*%%VOUCHER_JSON_END%%',
            reply_text, re.DOTALL,
        )
        if json_match:
            try:
                voucher_data = json.loads(json_match.group(1))
                if action == AgentAction.NONE:
                    action = AgentAction.PREVIEW
            except Exception as e:
                logger.warning("凭证 JSON 解析失败: %s", e)

        # Fallback: 尝试从回复中提取 ```json ... ``` 代码块中的凭证 JSON
        if voucher_data is None:
            code_block_match = re.search(
                r'```(?:json)?\s*(\{[\s\S]*?"entries"[\s\S]*?\})\s*```',
                reply_text,
            )
            if code_block_match:
                try:
                    candidate = json.loads(code_block_match.group(1))
                    if isinstance(candidate, dict) and "entries" in candidate:
                        voucher_data = candidate
                        if action == AgentAction.NONE:
                            action = AgentAction.PREVIEW
                except Exception:
                    pass

        # Fallback 2: 尝试提取回复中任意包含 entries 的 JSON 对象
        if voucher_data is None:
            brace_match = re.search(
                r'(\{[^{}]*"entries"\s*:\s*\[[\s\S]*?\]\s*[^{}]*\})',
                reply_text,
            )
            if brace_match:
                try:
                    candidate = json.loads(brace_match.group(1))
                    if isinstance(candidate, dict) and "entries" in candidate:
                        voucher_data = candidate
                        if action == AgentAction.NONE:
                            action = AgentAction.PREVIEW
                except Exception:
                    pass

        if mcp_voucher and action != AgentAction.POSTED:
            action = AgentAction.POSTED

        if voucher_data and expected_total_amount is not None:
            current_total = _voucher_total_debit(voucher_data)
            if abs(current_total - expected_total_amount) > Decimal("0.01"):
                submitter = ""
                if isinstance(known_profile, dict):
                    submitter = str(known_profile.get("submitter") or "")
                voucher_data = _force_voucher_total(voucher_data, expected_total_amount, submitter)
                action = AgentAction.PREVIEW
                total_label = "用户人工确认总额" if expected_total_source == "manual" else "多票据汇总总额"
                reply_text += (
                    f"\n\n系统已按{total_label} {_round2(expected_total_amount)} "
                    "自动校正凭证金额，请在预览中确认。"
                )

        if voucher_data and isinstance(known_profile, dict):
            voucher_data = _apply_known_profile_to_voucher(voucher_data, known_profile)
        if voucher_data is not None:
            entries = voucher_data.get("entries") if isinstance(voucher_data, dict) else None
            if not isinstance(entries, list) or len(entries) == 0:
                voucher_data = None
                if action == AgentAction.PREVIEW:
                    action = AgentAction.NONE

        return AgentResponse(
            success=True,
            reply=reply_text,
            action=action,
            voucher_data=voucher_data,
            mcp_voucher=mcp_voucher,
        )

    def _get_or_create_sdk_client(self, session_id: str) -> ClaudeSDKClient:
        """Get or create a ClaudeSDKClient for the given session."""
        if session_id not in self._sdk_clients:
            self._sdk_clients[session_id] = self._create_sdk_client()
        return self._sdk_clients[session_id]

    def _create_sdk_client(self) -> ClaudeSDKClient:
        """Create a new ClaudeSDKClient with registered tools."""
        from agent_core._tools import get_sdk_tools

        tools = get_sdk_tools()
        mcp_server = create_sdk_mcp_server(
            name="finance-tools",
            version="2.0.0",
            tools=tools,
        )
        options = ClaudeAgentOptions(
            system_prompt=_SYSTEM_PROMPT,
            model=ANTHROPIC_MODEL,
            max_turns=self._config.max_turns,
            mcp_servers={
                "finance-tools": {
                    "type": "sdk",
                    "name": "finance-tools",
                    "instance": mcp_server,
                }
            },
            allowed_tools=[
                "mcp__finance-tools__ocr_invoice",
                "mcp__finance-tools__classify_account",
                "mcp__finance-tools__generate_mcp_voucher",
                "mcp__finance-tools__tax_calculate",
            ],
        )
        return ClaudeSDKClient(options=options)

    def get_capability(self) -> CapabilityDeclaration:
        """
        返回能力声明，供 Orchestrator Agent 发现和了解本 Agent 的能力。
        """
        return CapabilityDeclaration(
            agent_name="finance-reimbursement-agent",
            description="企业财务报销智能代理",
            supported_intents=[
                "invoice_reimbursement",
                "voucher_query",
                "batch_reimbursement",
            ],
            input_schema=AgentRequest.model_json_schema(),
            output_schema=AgentResponse.model_json_schema(),
        )

    def register_mcp_tools(self) -> list[dict]:
        """
        嵌入模式下将自身工具注册为 MCP 工具，供 Orchestrator Agent 发现和调用。

        Returns:
            MCP 工具定义列表，每个工具包含 name、description、input_schema。
        """
        if self._mode != AgentMode.EMBEDDED:
            logger.warning(
                "register_mcp_tools called in %s mode; "
                "MCP tool registration is intended for embedded mode.",
                self._mode.value,
            )
            return []

        logger.info("Registering %d MCP tools for embedded mode", len(_MCP_TOOL_DEFINITIONS))
        return list(_MCP_TOOL_DEFINITIONS)

    async def _fire_event(self, event_name: str, data: dict) -> None:
        """Fire an event callback if registered."""
        callback = getattr(self, event_name, None)
        if callback is not None:
            try:
                result = callback(data)
                # Support both sync and async callbacks
                if hasattr(result, "__await__"):
                    await result
            except Exception as e:
                logger.error("Event callback %s error: %s", event_name, str(e))
