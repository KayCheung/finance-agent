"""
main.py
FastAPI 网关 - 精简路由层，仅路由定义，业务逻辑委托给 AgentCore。

集成 Session_Store：请求进入时获取或创建会话，响应返回前同步会话状态。

需求: 3.6, 3.7, 7.6, 8.2, 8.3, 8.5, 12.1
"""
import sys
if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    import os
    os.environ["ANYIO_BACKEND"] = "asyncio"
    # 禁用 PaddlePaddle OneDNN 和 PIR，规避 Windows CPU 上的兼容性崩溃
    os.environ["FLAGS_use_mkldnn"] = "0"
    os.environ["FLAGS_enable_pir_api"] = "0"
    os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"

import base64
import asyncio
import logging
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from agent_core.config import load_config, AppConfig
from agent_core.core import AgentCore
from agent_core.models import (
    AgentMode,
    AgentRequest,
    SessionData,
    VoucherRecord,
    VoucherEntry,
    ApprovalStatus,
)
from extensions.oa_connector import OAConnector, OAConfig as OAConnectorConfig
from extensions.submission_gateway import SubmissionGateway, create_submission_gateway
from storage.session_store import SessionStore
from storage.voucher_repository import VoucherRepository, VoucherQuery
from tools.voucher_type_resolver import VoucherTypeResolver

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── App configuration ──
_config: AppConfig = load_config()

app = FastAPI(title="企业财务报销智能 Agent", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Lazy-initialized core components ──
_agent_core: Optional[AgentCore] = None
_session_store: Optional[SessionStore] = None
_voucher_repo: Optional[VoucherRepository] = None
_oa_connector: Optional[OAConnector] = None
_voucher_type_resolver: Optional[VoucherTypeResolver] = None
_submission_gateway: Optional[SubmissionGateway] = None
_VOUCHER_TYPES = {"记", "收", "付", "转", "调", "冲", "费用", "成本", "收入", "税务"}


def _get_agent_core() -> AgentCore:
    """Lazy-initialize AgentCore."""
    global _agent_core
    if _agent_core is None:
        mode = AgentMode(_config.agent.mode)
        _agent_core = AgentCore(mode=mode, config=_config.agent, ocr_config=_config.ocr)
    return _agent_core


def _get_session_store() -> SessionStore:
    """Lazy-initialize SessionStore from config."""
    global _session_store
    if _session_store is None:
        backend = SessionStore.create_backend_from_config(
            _config.session.backend_class,
            storage_dir=_config.session.storage_dir,
        )
        _session_store = SessionStore(backend)
    return _session_store


def _get_voucher_repo() -> VoucherRepository:
    """Lazy-initialize VoucherRepository."""
    global _voucher_repo
    if _voucher_repo is None:
        storage_file = (_config.voucher_repo.storage_file or "").strip()
        _voucher_repo = VoucherRepository(storage_path=storage_file or None)
    return _voucher_repo


def _get_oa_connector() -> OAConnector:
    """Lazy-initialize OAConnector from config."""
    global _oa_connector
    if _oa_connector is None:
        oa_cfg = OAConnectorConfig(
            api_url=_config.oa.api_url,
            auth_type=_config.oa.auth_type,
            auth_credentials=_config.oa.auth_credentials,
            field_mapping=_config.oa.field_mapping,
            webhook_secret=_config.oa.webhook_secret,
            use_webhook=_config.oa.use_webhook,
            polling_interval=_config.oa.polling_interval,
            submit_timeout=_config.oa.submit_timeout,
        )
        _oa_connector = OAConnector(config=oa_cfg)
    return _oa_connector


def _get_voucher_type_resolver() -> VoucherTypeResolver:
    """Lazy-initialize voucher type resolver from config."""
    global _voucher_type_resolver
    if _voucher_type_resolver is None:
        _voucher_type_resolver = VoucherTypeResolver(
            rag_enabled=(_config.rag.enabled and _config.voucher_type.use_rag_fallback),
            rag_knowledge_base_dir=_config.rag.knowledge_base_dir,
            rag_knowledge_file=_config.voucher_type.rag_knowledge_file,
            rag_min_score=_config.voucher_type.rag_min_score,
            enable_llm_fallback=_config.voucher_type.enable_llm_fallback,
        )
    return _voucher_type_resolver


def _get_submission_gateway() -> Optional[SubmissionGateway]:
    """Lazy-initialize external submission gateway."""
    global _submission_gateway
    if _submission_gateway is not None:
        return _submission_gateway

    # Backward compatibility:
    # - submission.enabled=true uses configured unified gateway.
    # - if submission is disabled but oa.enabled=true, still use OA channel.
    if _config.submission.enabled:
        channel = _config.submission.channel
    elif _config.oa.enabled:
        channel = "oa"
    else:
        return None

    oa_connector = _get_oa_connector() if channel.strip().lower() == "oa" else None
    _submission_gateway = create_submission_gateway(channel=channel, oa_connector=oa_connector)
    return _submission_gateway


def _normalize_accounting_date(raw: object) -> str:
    text = str(raw or "").strip()
    if not text:
        return datetime.now().strftime("%Y%m%d")
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(text[:10] if fmt != "%Y%m%d" else text[:8], fmt).strftime("%Y%m%d")
        except ValueError:
            continue
    m = re.search(r"(\d{4})[-/]?(\d{2})[-/]?(\d{2})", text)
    if m:
        return f"{m.group(1)}{m.group(2)}{m.group(3)}"
    return datetime.now().strftime("%Y%m%d")


def _extract_known_profile(messages: list[dict]) -> dict:
    profile = {"department": "", "usage": "", "submitter": ""}
    patterns = {
        "department": re.compile(r"(?:部门|所属部门|归属部门)\s*[:：]?\s*([^\s，。,；;]+)"),
        "usage": re.compile(r"(?:用途|费用用途|报销用途|费用类型)\s*[:：]?\s*([^\s，。,；;]+)"),
        "submitter": re.compile(r"(?:报销人|提交人|申请人|经办人)(?:姓名)?\s*[:：]?\s*([^\s，。,；;]+)"),
    }

    for msg in reversed(messages):
        if not isinstance(msg, dict):
            continue

        voucher = msg.get("voucher")
        if isinstance(voucher, dict):
            if not profile["department"] and voucher.get("department"):
                profile["department"] = str(voucher.get("department"))
            if not profile["usage"] and voucher.get("usage"):
                profile["usage"] = str(voucher.get("usage"))
            if not profile["submitter"] and voucher.get("submitter"):
                profile["submitter"] = str(voucher.get("submitter"))

        if msg.get("role") != "user":
            continue
        content = str(msg.get("content") or "")

        # Heuristic for plain-text profile inputs like:
        # "市场部 李世民 差旅费" / "科技部 差旅费 张三"
        tokens = [t.strip() for t in re.split(r"[\s,，;；]+", content) if t.strip()]
        if tokens:
            if not profile["department"]:
                dept = next((t for t in tokens if re.search(r"(部|中心|处|科|室|组)$", t)), "")
                if dept:
                    profile["department"] = dept
            if not profile["usage"]:
                usage = next((t for t in tokens if re.search(r"(用途|费|差旅|交通|办公|招待|住宿|餐饮)", t)), "")
                if usage:
                    profile["usage"] = usage.replace("用途", "").replace("：", "").replace(":", "") or usage
            if not profile["submitter"]:
                name_candidates = [
                    t for t in tokens
                    if re.fullmatch(r"[\u4e00-\u9fa5]{2,4}", t)
                    and t != profile["department"]
                    and t != profile["usage"]
                ]
                if name_candidates:
                    profile["submitter"] = name_candidates[0]

        for key, pattern in patterns.items():
            if profile[key]:
                continue
            m = pattern.search(content)
            if m:
                profile[key] = m.group(1)

        if all(profile.values()):
            break
    return profile


def _build_session_context(messages: list[dict]) -> dict:
    known_amount = {"total_amount": None, "line_amounts": []}
    expr_pattern = re.compile(r"^\s*\d+(?:\.\d+)?(?:\s*\+\s*\d+(?:\.\d+)?)+\s*$")
    total_pattern = re.compile(r"(?:总金额|合计|小计)\s*[:：]?\s*(\d+(?:\.\d{1,2})?)")
    amount_list_pattern = re.compile(r"\d+(?:\.\d{1,2})?")

    for msg in reversed(messages):
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        content = str(msg.get("content") or "").strip()
        if not content:
            continue

        m_total = total_pattern.search(content)
        if m_total:
            try:
                known_amount["total_amount"] = str(Decimal(m_total.group(1)).quantize(Decimal("0.01")))
                break
            except InvalidOperation:
                pass

        if expr_pattern.match(content):
            try:
                nums = [Decimal(x) for x in amount_list_pattern.findall(content)]
                if nums:
                    known_amount["line_amounts"] = [str(n.quantize(Decimal("0.01"))) for n in nums]
                    known_amount["total_amount"] = str(sum(nums, Decimal("0")).quantize(Decimal("0.01")))
                    break
            except InvalidOperation:
                pass

    history_messages: list[dict] = []
    for msg in messages[-16:]:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "").strip()
        content = str(msg.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        content = re.sub(r"%%VOUCHER_JSON_START%%[\s\S]*?%%VOUCHER_JSON_END%%", "", content).strip()
        if not content:
            continue
        history_messages.append({"role": role, "content": content[:220]})

    return {
        "known_profile": _extract_known_profile(messages),
        "known_amount": known_amount,
        "history_messages": history_messages,
    }


def _infer_voucher_type(voucher_data: dict) -> str:
    resolver = _get_voucher_type_resolver()
    resolved = resolver.resolve(voucher_data)
    if resolved in _VOUCHER_TYPES:
        return resolved
    return "记"


def _parse_voucher_sequence(voucher_id: str, voucher_type: str, accounting_date: str) -> Optional[int]:
    if not voucher_id:
        return None
    pattern = rf"^{re.escape(voucher_type)}[-_]?{accounting_date}[-_]?(\d+)$"
    match = re.match(pattern, voucher_id.strip())
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


async def _next_voucher_sequence(voucher_type: str, accounting_date: str) -> int:
    store = _get_session_store()
    summaries = await store._backend.list()
    max_seq = 0
    for summary in summaries:
        session = await store._backend.load(summary.session_id)
        if not session:
            continue
        for msg in session.messages:
            if not isinstance(msg, dict):
                continue
            voucher = msg.get("voucher")
            if not isinstance(voucher, dict):
                continue
            seq = _parse_voucher_sequence(str(voucher.get("voucher_id") or ""), voucher_type, accounting_date)
            if seq and seq > max_seq:
                max_seq = seq
    return max_seq + 1


async def _apply_voucher_number_rule(voucher_data: dict, force_regenerate: bool = False) -> dict:
    voucher_type = _infer_voucher_type(voucher_data)
    accounting_date = _normalize_accounting_date(
        voucher_data.get("accounting_date")
        or voucher_data.get("voucher_date")
        or voucher_data.get("date")
        or voucher_data.get("invoice_date")
    )
    current_id = str(voucher_data.get("voucher_id") or "")
    current_seq = _parse_voucher_sequence(current_id, voucher_type, accounting_date)

    if force_regenerate or current_seq is None:
        next_seq = await _next_voucher_sequence(voucher_type, accounting_date)
        voucher_data["voucher_id"] = f"{voucher_type}{accounting_date}{next_seq:04d}"
    voucher_data["voucher_type"] = voucher_type
    voucher_data["accounting_date"] = accounting_date
    return voucher_data


def _to_voucher_record(voucher_data: dict, session_id: str, now: datetime) -> VoucherRecord:
    entries: list[VoucherEntry] = []
    for item in voucher_data.get("entries") or []:
        if not isinstance(item, dict):
            continue
        entries.append(
            VoucherEntry(
                account_code=str(item.get("account_code") or ""),
                account_name=str(item.get("account_name") or ""),
                debit=item.get("debit") or 0,
                credit=item.get("credit") or 0,
            )
        )

    total_amount = voucher_data.get("total_debit")
    if total_amount is None:
        total_amount = sum((e.debit for e in entries), Decimal("0"))

    return VoucherRecord(
        voucher_id=str(voucher_data.get("voucher_id") or ""),
        created_at=now,
        department=str(voucher_data.get("department") or ""),
        submitter=str(voucher_data.get("submitter") or ""),
        summary=str(voucher_data.get("summary") or ""),
        usage=str(voucher_data.get("usage") or ""),
        entries=entries,
        total_amount=total_amount,
        approval_status=ApprovalStatus.PENDING,
        session_id=session_id,
        expense_type=str(voucher_data.get("voucher_type") or ""),
    )


# ── Static file serving ──

@app.get("/")
async def index():
    """Serve the legacy frontend."""
    return FileResponse("index.html")


# ── Agent chat endpoint ──

@app.post("/agent/chat")
async def chat(
    session_id: str = Form(...),
    message: str = Form(default=""),
    file: UploadFile = File(default=None),
    files: list[UploadFile] = File(default=[]),
):
    """
    Main chat endpoint. Delegates to AgentCore.invoke().
    Integrates Session_Store: get/create session on entry, sync on exit.
    """
    store = _get_session_store()
    core = _get_agent_core()

    # Session_Store integration: get or create session (Req 3.6, 3.7)
    session = await store.get_or_create(session_id)
    message_text = (message or "").strip()

    # Handle voucher confirmation as a built-in system action.
    # This avoids routing confirmation prompts to LLM/tool selection.
    confirm_phrases = {"确认", "确认凭证", "确认提交"}
    is_confirm_action = (
        message_text in confirm_phrases
        or "generate_mcp_voucher" in message_text
    )
    if is_confirm_action:
        now = datetime.now()
        now_iso = now.isoformat()
        session.last_active = now
        if message_text:
            session.messages.append({"role": "user", "content": message_text, "time": now_iso})

        confirmed_voucher: Optional[dict] = None
        latest_assistant_msg: Optional[dict] = None
        for msg in reversed(session.messages):
            if msg.get("role") == "assistant":
                latest_assistant_msg = msg
                break

        if latest_assistant_msg and not latest_assistant_msg.get("confirmed"):
            voucher = latest_assistant_msg.get("voucher")
            if isinstance(voucher, dict):
                latest_assistant_msg["voucher"] = await _apply_voucher_number_rule(voucher, force_regenerate=False)
                confirmed_voucher = latest_assistant_msg["voucher"]
                latest_assistant_msg["confirmed"] = True

        if confirmed_voucher is None:
            confirm_reply = "未找到可确认的凭证，请先生成凭证预览。"
            session.messages.append({
                "role": "assistant",
                "content": confirm_reply,
                "time": now_iso,
            })
            await store.update(session)
            return {
                "success": False,
                "reply": confirm_reply,
                "action": "error",
                "voucher_data": None,
                "mcp_voucher": None,
                "batch_result": None,
                "errors": [confirm_reply],
            }

        repo = _get_voucher_repo()
        record = _to_voucher_record(confirmed_voucher, session.session_id, now)
        submit_error: Optional[str] = None
        approval_id: Optional[str] = None
        submission_channel: Optional[str] = None
        gateway = _get_submission_gateway()
        if gateway is not None:
            submission_channel = gateway.channel
            max_attempts = max(1, int(_config.submission.retry_count) + 1)
            backoff_ms = max(0, int(_config.submission.retry_backoff_ms))

            submit_result = None
            for attempt in range(1, max_attempts + 1):
                submit_result = await gateway.submit_voucher(confirmed_voucher)
                if submit_result.success:
                    break
                submit_error = submit_result.error or f"{submission_channel}提交失败"
                logger.warning(
                    "External submission failed [channel=%s, voucher_id=%s, attempt=%d/%d]: %s",
                    submission_channel,
                    record.voucher_id,
                    attempt,
                    max_attempts,
                    submit_error,
                )
                if attempt < max_attempts and backoff_ms > 0:
                    await asyncio.sleep(backoff_ms / 1000)

            if submit_result and submit_result.success:
                submit_error = None
                approval_id = submit_result.approval_id
                if approval_id:
                    record.approval_id = approval_id
        await repo.save(record)

        confirm_reply = "凭证已确认，已加入已确认凭证列表。"
        if submission_channel and approval_id:
            confirm_reply = f"{confirm_reply} 已提交{submission_channel.upper()}审批，审批单号：{approval_id}。"
        elif submission_channel and submit_error:
            confirm_reply = f"{confirm_reply} {submission_channel.upper()}提交失败：{submit_error}。"

        session.messages.append({
            "role": "assistant",
            "content": confirm_reply,
            "time": now_iso,
        })
        await store.update(session)

        return {
            "success": submit_error is None,
            "reply": confirm_reply,
            "action": "error" if submit_error else "posted",
            "voucher_data": None,
            "mcp_voucher": None,
            "batch_result": None,
            "submission_channel": submission_channel,
            "external_id": approval_id,
            "errors": [submit_error] if submit_error else [],
        }

    # Prepare image data
    images = []
    uploaded_images: list[dict] = []
    upload_candidates: list[UploadFile] = []
    if files:
        upload_candidates.extend([f for f in files if f and f.filename])
    if file and file.filename:
        upload_candidates.append(file)

    for up in upload_candidates:
        content = await up.read()
        image_b64 = base64.b64encode(content).decode()
        images.append({"image_base64": image_b64, "filename": up.filename})
        uploaded_images.append(
            {
                "image_base64": image_b64,
                "image_mime": up.content_type or "application/octet-stream",
                "image_filename": up.filename,
            }
        )

    # Build context from history + current user turn so the agent can
    # immediately see freshly provided profile/amount info in this same round.
    context_messages = list(session.messages)
    if message_text or uploaded_images:
        context_user_content = message_text
        if not context_user_content and uploaded_images:
            if len(uploaded_images) == 1:
                context_user_content = f"上传文件: {uploaded_images[0].get('image_filename', '')}"
            else:
                names = ", ".join(str(x.get("image_filename", "")) for x in uploaded_images)
                context_user_content = f"上传文件({len(uploaded_images)}): {names}"
        context_messages.append({"role": "user", "content": context_user_content})

    # Build structured request and delegate to AgentCore
    request = AgentRequest(
        intent="invoice_reimbursement" if images else "chat",
        session_id=session.session_id,
        message=message,
        images=images,
        session_context=_build_session_context(context_messages),
    )

    try:
        response = await core.invoke(request)
    except Exception as e:
        logger.exception("Agent 处理失败")
        raise HTTPException(500, str(e))

    # Session_Store integration: sync session state before response (Req 3.5, 8.5)
    now = datetime.now()
    now_iso = now.isoformat()
    session.last_active = now
    if message_text or uploaded_images:
        user_content = message_text
        if not user_content and uploaded_images:
            if len(uploaded_images) == 1:
                user_content = f"上传文件: {uploaded_images[0].get('image_filename', '')}"
            else:
                names = ", ".join(str(x.get("image_filename", "")) for x in uploaded_images)
                user_content = f"上传文件({len(uploaded_images)}): {names}"
        user_message = {"role": "user", "content": user_content, "time": now_iso}
        if uploaded_images:
            user_message.update(uploaded_images[0])
            user_message["image_list"] = uploaded_images
        session.messages.append(user_message)
        if session.metadata is None:
            session.metadata = {}
        if not str(session.metadata.get("title") or "").strip():
            auto_title = message_text.strip()
            if not auto_title:
                auto_title = f"上传票据-{uploaded_images[0].get('image_filename', '')}" if uploaded_images else "新会话"
            session.metadata["title"] = auto_title[:24]

    assistant_message = {"role": "assistant", "content": response.reply, "time": now_iso}
    if response.voucher_data:
        response.voucher_data = await _apply_voucher_number_rule(response.voucher_data, force_regenerate=False)
        assistant_message["voucher"] = response.voucher_data
        assistant_message["confirmed"] = False
    session.messages.append(assistant_message)
    if response.voucher_data:
        session.voucher_state = response.voucher_data
    await store.update(session)

    return response.model_dump(mode="json")


# ── Session management endpoints (Req 8.3) ──

@app.get("/sessions")
async def list_sessions(
    search: Optional[str] = Query(default=None),
    include_archived: bool = Query(default=False),
):
    """List all sessions with summary info."""
    store = _get_session_store()
    sessions = await store._backend.list()

    keyword = (search or "").strip().lower()
    filtered = []
    for s in sessions:
        if not include_archived and bool(getattr(s, "archived", False)):
            continue
        if keyword:
            haystack = " ".join(
                [
                    s.session_id.lower(),
                    str(getattr(s, "title", "")).lower(),
                    str(getattr(s, "preview", "")).lower(),
                ]
            )
            if keyword not in haystack:
                continue
        filtered.append(s)

    filtered.sort(key=lambda s: (not bool(getattr(s, "pinned", False)), -s.last_active.timestamp()))
    return [s.model_dump(mode="json") for s in filtered]


@app.post("/sessions")
async def create_session(payload: dict):
    """Create a new empty session."""
    store = _get_session_store()
    now = datetime.now()
    session = SessionData(
        session_id=str(payload.get("session_id") or ""),
        created_at=now,
        last_active=now,
        messages=[],
        metadata={},
    )
    if not session.session_id:
        session = SessionStore._create_new_session()

    title = str(payload.get("title") or "").strip()
    if title:
        session.metadata["title"] = title
    await store.update(session)
    return session.model_dump(mode="json")


@app.get("/sessions/{session_id}")
async def load_session(session_id: str):
    """Load a specific session by ID."""
    store = _get_session_store()
    session = await store._backend.load(session_id)
    if session is None:
        raise HTTPException(404, f"Session {session_id} not found")
    return session.model_dump(mode="json")


@app.patch("/sessions/{session_id}")
async def patch_session(session_id: str, payload: dict):
    """Patch session metadata (title/pinned/archived)."""
    store = _get_session_store()
    session = await store._backend.load(session_id)
    if session is None:
        raise HTTPException(404, f"Session {session_id} not found")

    if session.metadata is None:
        session.metadata = {}
    metadata = dict(session.metadata)

    if "title" in payload:
        metadata["title"] = str(payload.get("title") or "").strip()
    if "pinned" in payload:
        metadata["pinned"] = bool(payload.get("pinned"))
    if "archived" in payload:
        metadata["archived"] = bool(payload.get("archived"))

    session.metadata = metadata
    await store.update(session)
    return session.model_dump(mode="json")


@app.delete("/agent/session/{session_id}")
async def delete_session(session_id: str):
    """Delete a session."""
    store = _get_session_store()
    await store.remove(session_id)
    return {"cleared": True}


# ── Voucher query endpoints (Req 8.2) ──

@app.get("/vouchers")
async def query_vouchers(
    voucher_id: Optional[str] = Query(default=None),
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
    department: Optional[str] = Query(default=None),
    submitter: Optional[str] = Query(default=None),
    keyword: Optional[str] = Query(default=None),
):
    """Query vouchers with optional filters."""
    from datetime import date

    repo = _get_voucher_repo()
    q = VoucherQuery(
        voucher_id=voucher_id,
        date_from=date.fromisoformat(date_from) if date_from else None,
        date_to=date.fromisoformat(date_to) if date_to else None,
        department=department,
        submitter=submitter,
        keyword=keyword,
    )
    results = await repo.query(q)
    return [v.model_dump(mode="json") for v in results]


@app.get("/vouchers/{voucher_id}")
async def get_voucher(voucher_id: str):
    """Get a specific voucher by ID."""
    repo = _get_voucher_repo()
    voucher = await repo.get_by_id(voucher_id)
    if voucher is None:
        raise HTTPException(404, f"Voucher {voucher_id} not found")
    return voucher.model_dump(mode="json")


# ── OA Webhook callback endpoint (Req 7.6) ──

@app.post("/oa/callback")
async def oa_callback(
    payload: dict,
    x_oa_signature: str = Header(default=""),
):
    """
    OA 系统审批状态变更 Webhook 回调端点。
    校验请求签名，更新本地凭证审批状态。
    """
    connector = _get_oa_connector()
    repo = _get_voucher_repo()

    try:
        status = await connector.handle_webhook(payload, x_oa_signature)
    except ValueError as e:
        raise HTTPException(403, str(e))

    # Update voucher approval status if approval_id is present
    approval_id = payload.get("approval_id")
    voucher_id = payload.get("voucher_id")
    if voucher_id and status:
        voucher = await repo.get_by_id(voucher_id)
        if voucher:
            voucher.approval_status = status
            if approval_id:
                voucher.approval_id = approval_id
            await repo.save(voucher)

    return {"received": True, "status": status.value if status else None}


# ── Health check ──

@app.get("/agent/health")
async def health():
    return {"status": "ok", "agent": "finance-reimbursement-v2-sdk"}


# ── Entry point ──

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=False, loop="asyncio")
