"""
tests/test_main.py
Tests for the refactored main.py gateway - slim routing layer + Session_Store integration.

Validates:
- Task 16.1: Routes delegate to AgentCore, OA callback, session/voucher endpoints
- Task 16.2: Session_Store integration (get_or_create on entry, sync on exit)
"""
import hashlib
import hmac
import json
import base64
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from httpx import AsyncClient, ASGITransport

from agent_core.models import (
    AgentResponse,
    AgentAction,
    ApprovalStatus,
    SubmitResult,
    SessionData,
    SessionSummary,
    VoucherEntry,
    VoucherRecord,
)


@pytest.fixture(autouse=True)
def reset_globals():
    """Reset lazy-initialized globals before each test."""
    import main
    main._agent_core = None
    main._session_store = None
    main._voucher_repo = None
    main._oa_connector = None
    main._submission_gateway = None
    yield


@pytest.fixture
def mock_session_store():
    """Create a mock SessionStore."""
    store = MagicMock()
    store.get_or_create = AsyncMock(return_value=SessionData(
        session_id="test-session",
        created_at=datetime(2024, 1, 1),
        last_active=datetime(2024, 1, 1),
        messages=[],
    ))
    store.update = AsyncMock()
    store.remove = AsyncMock()
    store._backend = MagicMock()
    store._backend.list = AsyncMock(return_value=[
        SessionSummary(
            session_id="s1",
            created_at=datetime(2024, 1, 1),
            last_active=datetime(2024, 1, 2),
            voucher_count=1,
        )
    ])
    store._backend.load = AsyncMock(return_value=SessionData(
        session_id="s1",
        created_at=datetime(2024, 1, 1),
        last_active=datetime(2024, 1, 2),
        messages=[{"role": "user", "content": "hello"}],
    ))
    return store


@pytest.fixture
def mock_agent_core():
    """Create a mock AgentCore."""
    core = MagicMock()
    core.invoke = AsyncMock(return_value=AgentResponse(
        success=True,
        reply="处理完成",
        action=AgentAction.NONE,
    ))
    return core


@pytest.fixture
def mock_voucher_repo():
    """Create a mock VoucherRepository."""
    repo = MagicMock()
    repo.query = AsyncMock(return_value=[])
    repo.get_by_id = AsyncMock(return_value=None)
    repo.save = AsyncMock()
    return repo


@pytest.fixture
def mock_oa_connector():
    """Create a mock OAConnector."""
    connector = MagicMock()
    connector.handle_webhook = AsyncMock(return_value=ApprovalStatus.APPROVED)
    return connector


@pytest.fixture
def app_with_mocks(mock_session_store, mock_agent_core, mock_voucher_repo, mock_oa_connector):
    """Inject mocks into main module globals."""
    import main
    main._session_store = mock_session_store
    main._agent_core = mock_agent_core
    main._voucher_repo = mock_voucher_repo
    main._oa_connector = mock_oa_connector
    main._submission_gateway = None
    return main.app


# ── Health endpoint ──

@pytest.mark.asyncio
async def test_health(app_with_mocks):
    transport = ASGITransport(app=app_with_mocks)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/agent/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["agent"] == "finance-reimbursement-v2-sdk"


# ── Chat endpoint (Task 16.1 + 16.2) ──

@pytest.mark.asyncio
async def test_chat_delegates_to_agent_core(
    app_with_mocks, mock_agent_core, mock_session_store
):
    """Chat endpoint should get/create session and delegate to AgentCore."""
    transport = ASGITransport(app=app_with_mocks)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/agent/chat",
            data={"session_id": "test-session", "message": "报销一张发票"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["reply"] == "处理完成"

    # Verify Session_Store integration (Task 16.2)
    mock_session_store.get_or_create.assert_called_once_with("test-session")
    mock_session_store.update.assert_called_once()

    # Verify AgentCore was called
    mock_agent_core.invoke.assert_called_once()


@pytest.mark.asyncio
async def test_chat_syncs_session_state(
    app_with_mocks, mock_session_store
):
    """Chat should append messages and sync session state before response."""
    transport = ASGITransport(app=app_with_mocks)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post(
            "/agent/chat",
            data={"session_id": "test-session", "message": "hello"},
        )

    # Check that update was called with session containing messages
    call_args = mock_session_store.update.call_args
    session = call_args[0][0]
    assert len(session.messages) == 2  # user + assistant
    assert session.messages[0]["role"] == "user"
    assert session.messages[0]["content"] == "hello"
    assert session.messages[1]["role"] == "assistant"
    assert session.metadata["title"] == "hello"


@pytest.mark.asyncio
async def test_chat_builds_context_with_current_user_turn(
    app_with_mocks, mock_agent_core
):
    """Current user message should be included in session_context for this turn."""
    transport = ASGITransport(app=app_with_mocks)
    msg = "部门:科技部 用途:差旅费 报销人:李世民"
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/agent/chat",
            data={"session_id": "test-session", "message": msg},
        )

    assert resp.status_code == 200
    assert mock_agent_core.invoke.called
    req = mock_agent_core.invoke.call_args[0][0]
    context = req.session_context or {}
    known_profile = context.get("known_profile") or {}
    assert "科技部" in str(known_profile.get("department") or "")
    assert known_profile.get("usage") == "差旅费"
    assert known_profile.get("submitter") == "李世民"


@pytest.mark.asyncio
async def test_chat_image_only_persists_user_message_with_image(
    app_with_mocks, mock_session_store
):
    """Image-only upload should still persist user message and image preview data."""
    transport = ASGITransport(app=app_with_mocks)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post(
            "/agent/chat",
            data={"session_id": "test-session", "message": ""},
            files={"file": ("invoice.png", b"abc", "image/png")},
        )

    call_args = mock_session_store.update.call_args
    session = call_args[0][0]
    assert len(session.messages) == 2  # user + assistant
    assert session.messages[0]["role"] == "user"
    assert session.messages[0]["content"] == "上传文件: invoice.png"
    assert session.messages[0]["image_filename"] == "invoice.png"
    assert session.messages[0]["image_mime"] == "image/png"
    assert session.messages[0]["image_base64"] == base64.b64encode(b"abc").decode()


@pytest.mark.asyncio
async def test_confirm_requires_latest_assistant_message_has_preview(
    app_with_mocks, mock_session_store, mock_voucher_repo
):
    """Confirm should fail if latest assistant message has no voucher preview."""
    session = SessionData(
        session_id="test-session",
        created_at=datetime(2024, 1, 1),
        last_active=datetime(2024, 1, 1),
        messages=[
            {
                "role": "assistant",
                "content": "旧凭证",
                "voucher": {
                    "voucher_id": "记202603300001",
                    "department": "市场部",
                    "submitter": "裴丽丽",
                    "summary": "旧凭证",
                    "usage": "差旅费",
                    "entries": [{"account_code": "6601", "account_name": "差旅费", "debit": 100, "credit": 0}],
                    "total_debit": 100,
                    "total_credit": 100,
                },
                "confirmed": False,
                "time": datetime.now().isoformat(),
            },
            {
                "role": "assistant",
                "content": "请补充信息后再生成凭证",
                "time": datetime.now().isoformat(),
            },
        ],
    )
    mock_session_store.get_or_create = AsyncMock(return_value=session)

    transport = ASGITransport(app=app_with_mocks)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/agent/chat",
            data={"session_id": "test-session", "message": "确认"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert data["action"] == "error"
    assert "未找到可确认的凭证" in data["reply"]
    mock_voucher_repo.save.assert_not_called()


@pytest.mark.asyncio
async def test_confirm_uses_submission_gateway_and_returns_external_fields(
    app_with_mocks, mock_session_store, mock_voucher_repo
):
    """Confirm flow should use unified submission gateway and return channel/external_id."""
    import main

    session = SessionData(
        session_id="test-session",
        created_at=datetime(2024, 1, 1),
        last_active=datetime(2024, 1, 1),
        messages=[
            {
                "role": "assistant",
                "content": "凭证预览",
                "voucher": {
                    "voucher_id": "记202603300001",
                    "department": "市场部",
                    "submitter": "裴丽丽",
                    "summary": "市场部裴丽丽差旅费",
                    "usage": "差旅费",
                    "entries": [
                        {"account_code": "6601", "account_name": "差旅费", "debit": 280.5, "credit": 0},
                        {"account_code": "2241", "account_name": "其他应付款-裴丽丽", "debit": 0, "credit": 280.5},
                    ],
                    "total_debit": 280.5,
                    "total_credit": 280.5,
                },
                "confirmed": False,
                "time": datetime.now().isoformat(),
            },
        ],
    )
    mock_session_store.get_or_create = AsyncMock(return_value=session)

    gateway = MagicMock()
    gateway.channel = "oa"
    gateway.submit_voucher = AsyncMock(return_value=SubmitResult(success=True, approval_id="AP-9001"))
    main._submission_gateway = gateway

    transport = ASGITransport(app=app_with_mocks)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/agent/chat",
            data={"session_id": "test-session", "message": "确认"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["action"] == "posted"
    assert data["submission_channel"] == "oa"
    assert data["external_id"] == "AP-9001"
    mock_voucher_repo.save.assert_called_once()


@pytest.mark.asyncio
async def test_confirm_submission_retries_when_enabled(
    app_with_mocks, mock_session_store
):
    """When submission.enabled=true, confirm should retry failed submissions."""
    import main

    session = SessionData(
        session_id="test-session",
        created_at=datetime(2024, 1, 1),
        last_active=datetime(2024, 1, 1),
        messages=[
            {
                "role": "assistant",
                "content": "凭证预览",
                "voucher": {
                    "voucher_id": "记202603300001",
                    "department": "市场部",
                    "submitter": "裴丽丽",
                    "summary": "市场部裴丽丽差旅费",
                    "usage": "差旅费",
                    "entries": [{"account_code": "6601", "account_name": "差旅费", "debit": 280.5, "credit": 0}],
                    "total_debit": 280.5,
                    "total_credit": 280.5,
                },
                "confirmed": False,
                "time": datetime.now().isoformat(),
            },
        ],
    )
    mock_session_store.get_or_create = AsyncMock(return_value=session)

    gateway = MagicMock()
    gateway.channel = "oa"
    gateway.submit_voucher = AsyncMock(side_effect=[
        SubmitResult(success=False, error="temporary error"),
        SubmitResult(success=True, approval_id="AP-RETRY"),
    ])
    main._submission_gateway = gateway

    old_enabled = main._config.submission.enabled
    old_retry = main._config.submission.retry_count
    old_backoff = main._config.submission.retry_backoff_ms
    main._config.submission.enabled = True
    main._config.submission.retry_count = 1
    main._config.submission.retry_backoff_ms = 0
    try:
        transport = ASGITransport(app=app_with_mocks)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/agent/chat",
                data={"session_id": "test-session", "message": "确认"},
            )
    finally:
        main._config.submission.enabled = old_enabled
        main._config.submission.retry_count = old_retry
        main._config.submission.retry_backoff_ms = old_backoff

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["external_id"] == "AP-RETRY"
    assert gateway.submit_voucher.call_count == 2


@pytest.mark.asyncio
async def test_chat_error_returns_500(
    app_with_mocks, mock_agent_core, mock_session_store
):
    """Chat should return 500 when AgentCore raises."""
    mock_agent_core.invoke = AsyncMock(side_effect=RuntimeError("boom"))
    transport = ASGITransport(app=app_with_mocks)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/agent/chat",
            data={"session_id": "s1", "message": "test"},
        )
    assert resp.status_code == 500


# ── Session management endpoints (Task 16.1) ──

@pytest.mark.asyncio
async def test_list_sessions(app_with_mocks, mock_session_store):
    transport = ASGITransport(app=app_with_mocks)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/sessions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["session_id"] == "s1"


@pytest.mark.asyncio
async def test_load_session(app_with_mocks, mock_session_store):
    transport = ASGITransport(app=app_with_mocks)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/sessions/s1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == "s1"
    assert len(data["messages"]) == 1


@pytest.mark.asyncio
async def test_load_session_not_found(app_with_mocks, mock_session_store):
    mock_session_store._backend.load = AsyncMock(return_value=None)
    transport = ASGITransport(app=app_with_mocks)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/sessions/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_session(app_with_mocks, mock_session_store):
    transport = ASGITransport(app=app_with_mocks)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.delete("/agent/session/s1")
    assert resp.status_code == 200
    assert resp.json()["cleared"] is True
    mock_session_store.remove.assert_called_once_with("s1")


@pytest.mark.asyncio
async def test_create_session(app_with_mocks, mock_session_store):
    transport = ASGITransport(app=app_with_mocks)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/sessions", json={"session_id": "s-new", "title": "差旅报销会话"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == "s-new"
    assert data["metadata"]["title"] == "差旅报销会话"
    mock_session_store.update.assert_called()


@pytest.mark.asyncio
async def test_patch_session_metadata(app_with_mocks, mock_session_store):
    session = SessionData(
        session_id="s1",
        created_at=datetime(2024, 1, 1),
        last_active=datetime(2024, 1, 2),
        messages=[{"role": "user", "content": "hello"}],
        metadata={},
    )
    mock_session_store._backend.load = AsyncMock(return_value=session)

    transport = ASGITransport(app=app_with_mocks)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.patch("/sessions/s1", json={"title": "新标题", "pinned": True})
    assert resp.status_code == 200
    data = resp.json()
    assert data["metadata"]["title"] == "新标题"
    assert data["metadata"]["pinned"] is True
    mock_session_store.update.assert_called_once()


@pytest.mark.asyncio
async def test_list_sessions_excludes_archived_by_default(app_with_mocks, mock_session_store):
    mock_session_store._backend.list = AsyncMock(return_value=[
        SessionSummary(
            session_id="s-active",
            created_at=datetime(2024, 1, 1),
            last_active=datetime(2024, 1, 3),
            voucher_count=1,
            archived=False,
            title="活跃会话",
        ),
        SessionSummary(
            session_id="s-archived",
            created_at=datetime(2024, 1, 1),
            last_active=datetime(2024, 1, 4),
            voucher_count=1,
            archived=True,
            title="归档会话",
        ),
    ])
    transport = ASGITransport(app=app_with_mocks)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/sessions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["session_id"] == "s-active"


# ── Voucher query endpoints (Task 16.1) ──

@pytest.mark.asyncio
async def test_query_vouchers_empty(app_with_mocks, mock_voucher_repo):
    transport = ASGITransport(app=app_with_mocks)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/vouchers")
    assert resp.status_code == 200
    assert resp.json() == []
    mock_voucher_repo.query.assert_called_once()


@pytest.mark.asyncio
async def test_query_vouchers_with_filters(app_with_mocks, mock_voucher_repo):
    transport = ASGITransport(app=app_with_mocks)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/vouchers",
            params={"department": "财务部", "date_from": "2024-01-01"},
        )
    assert resp.status_code == 200
    call_args = mock_voucher_repo.query.call_args[0][0]
    assert call_args.department == "财务部"


@pytest.mark.asyncio
async def test_get_voucher_not_found(app_with_mocks, mock_voucher_repo):
    transport = ASGITransport(app=app_with_mocks)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/vouchers/VOU-123")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_voucher_found(app_with_mocks, mock_voucher_repo):
    voucher = VoucherRecord(
        voucher_id="VOU-123",
        created_at=datetime(2024, 1, 1),
        department="财务部",
        submitter="张三",
        summary="差旅费报销",
        usage="出差",
        entries=[VoucherEntry(account_code="6601", account_name="差旅费", debit=Decimal("1000"))],
        total_amount=Decimal("1000"),
    )
    mock_voucher_repo.get_by_id = AsyncMock(return_value=voucher)
    transport = ASGITransport(app=app_with_mocks)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/vouchers/VOU-123")
    assert resp.status_code == 200
    assert resp.json()["voucher_id"] == "VOU-123"


# ── OA Webhook callback endpoint (Task 16.1) ──

@pytest.mark.asyncio
async def test_oa_callback_success(app_with_mocks, mock_oa_connector, mock_voucher_repo):
    """Valid webhook should update voucher status."""
    voucher = VoucherRecord(
        voucher_id="VOU-001",
        created_at=datetime(2024, 1, 1),
        department="财务部",
        submitter="张三",
        summary="报销",
        usage="出差",
        entries=[],
        total_amount=Decimal("100"),
    )
    mock_voucher_repo.get_by_id = AsyncMock(return_value=voucher)

    transport = ASGITransport(app=app_with_mocks)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/oa/callback",
            json={"voucher_id": "VOU-001", "approval_id": "AP-001", "approval_status": "approved"},
            headers={"x-oa-signature": "test-sig"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["received"] is True
    assert data["status"] == "approved"

    # Verify voucher was updated and saved
    mock_voucher_repo.save.assert_called_once()


@pytest.mark.asyncio
async def test_oa_callback_invalid_signature(app_with_mocks, mock_oa_connector):
    """Invalid signature should return 403."""
    mock_oa_connector.handle_webhook = AsyncMock(
        side_effect=ValueError("Invalid webhook signature")
    )
    transport = ASGITransport(app=app_with_mocks)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/oa/callback",
            json={"voucher_id": "VOU-001"},
            headers={"x-oa-signature": "bad-sig"},
        )
    assert resp.status_code == 403


# ── Lazy initialization ──

def test_lazy_init_agent_core():
    """AgentCore should be lazily initialized."""
    import main
    main._agent_core = None
    core = main._get_agent_core()
    assert core is not None
    # Second call returns same instance
    assert main._get_agent_core() is core


def test_lazy_init_voucher_repo():
    """VoucherRepository should be lazily initialized."""
    import main
    main._voucher_repo = None
    repo = main._get_voucher_repo()
    assert repo is not None
    assert main._get_voucher_repo() is repo
