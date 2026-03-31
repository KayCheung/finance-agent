"""
tests/test_oa_connector.py
OA_Connector 单元测试
"""
import hashlib
import hmac
import json

import pytest
import pytest_asyncio

from extensions.oa_connector import OAConfig, OAConnector
from agent_core.models import ApprovalStatus


def _sign(payload: dict, secret: str) -> str:
    """Helper: compute HMAC-SHA256 signature for a payload."""
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


@pytest.fixture
def connector():
    config = OAConfig(
        api_url="http://oa.internal/api",
        webhook_secret="test-secret",
        use_webhook=True,
        polling_interval=30,
    )
    return OAConnector(config)


# ── submit_voucher ──

@pytest.mark.asyncio
async def test_submit_voucher_returns_submit_result(connector):
    """submit_voucher returns a SubmitResult (stub returns failure)."""
    result = await connector.submit_voucher({"voucher_id": "V001", "amount": 100})
    assert result.success is False
    assert result.error is not None


# ── handle_webhook: valid signature ──

@pytest.mark.asyncio
async def test_handle_webhook_valid_signature(connector):
    """Valid HMAC-SHA256 signature → returns ApprovalStatus."""
    payload = {"approval_id": "AP-001", "approval_status": "approved"}
    sig = _sign(payload, "test-secret")
    status = await connector.handle_webhook(payload, sig)
    assert status == ApprovalStatus.APPROVED


@pytest.mark.asyncio
async def test_handle_webhook_rejected_status(connector):
    payload = {"approval_id": "AP-002", "approval_status": "rejected"}
    sig = _sign(payload, "test-secret")
    status = await connector.handle_webhook(payload, sig)
    assert status == ApprovalStatus.REJECTED


@pytest.mark.asyncio
async def test_handle_webhook_returned_status(connector):
    payload = {"approval_id": "AP-003", "approval_status": "returned"}
    sig = _sign(payload, "test-secret")
    status = await connector.handle_webhook(payload, sig)
    assert status == ApprovalStatus.RETURNED


# ── handle_webhook: invalid signature ──

@pytest.mark.asyncio
async def test_handle_webhook_invalid_signature_raises(connector):
    """Invalid signature → raises ValueError."""
    payload = {"approval_id": "AP-001", "approval_status": "approved"}
    with pytest.raises(ValueError, match="Invalid webhook signature"):
        await connector.handle_webhook(payload, "bad-signature")


# ── poll_status ──

@pytest.mark.asyncio
async def test_poll_status_returns_pending(connector):
    """Stub poll_status returns PENDING."""
    status = await connector.poll_status("AP-001")
    assert status == ApprovalStatus.PENDING


# ── sync_mode ──

def test_sync_mode_webhook():
    config = OAConfig(use_webhook=True)
    assert OAConnector(config).sync_mode == "webhook"


def test_sync_mode_polling():
    """Webhook unavailable → fallback to polling mode (需求 7.7)."""
    config = OAConfig(use_webhook=False)
    conn = OAConnector(config)
    assert conn.sync_mode == "polling"


# ── field mapping ──

def test_field_mapping():
    config = OAConfig(field_mapping={"voucher_id": "doc_no", "amount": "total_amount"})
    conn = OAConnector(config)
    mapped = conn._map_fields({"voucher_id": "V001", "amount": 500, "extra": "ignored"})
    assert mapped == {"doc_no": "V001", "total_amount": 500}


def test_field_mapping_empty():
    config = OAConfig(field_mapping={})
    conn = OAConnector(config)
    voucher = {"voucher_id": "V001"}
    assert conn._map_fields(voucher) == voucher


# ── Property-Based Tests (hypothesis) ──

from hypothesis import given, settings, strategies as st


# ── Property 15: Webhook 签名校验 ──
# **Validates: Requirements 7.6**

@st.composite
def payload_and_secret(draw):
    """Generate random payload dicts and a random secret string."""
    keys = draw(st.lists(st.text(min_size=1, max_size=10, alphabet="abcdefghijklmnopqrstuvwxyz"), min_size=1, max_size=5, unique=True))
    values = draw(st.lists(st.text(min_size=0, max_size=20), min_size=len(keys), max_size=len(keys)))
    payload = dict(zip(keys, values))
    secret = draw(st.text(min_size=1, max_size=50))
    return payload, secret


@given(data=payload_and_secret())
@settings(max_examples=100)
@pytest.mark.asyncio
async def test_property15_webhook_signature_correct_accepted(data):
    """Property 15: correct HMAC-SHA256 signature is accepted."""
    payload, secret = data
    config = OAConfig(webhook_secret=secret, use_webhook=True)
    conn = OAConnector(config)
    sig = _sign(payload, secret)
    # Correct signature → _verify_signature returns True
    assert conn._verify_signature(payload, sig) is True


@given(data=payload_and_secret(), bad_sig=st.text(min_size=1, max_size=64, alphabet="0123456789abcdef"))
@settings(max_examples=100)
@pytest.mark.asyncio
async def test_property15_webhook_signature_mismatch_rejected(data, bad_sig):
    """Property 15: mismatched signature is rejected."""
    payload, secret = data
    correct_sig = _sign(payload, secret)
    # Skip if bad_sig accidentally equals the correct signature
    if bad_sig == correct_sig:
        return
    config = OAConfig(webhook_secret=secret, use_webhook=True)
    conn = OAConnector(config)
    assert conn._verify_signature(payload, bad_sig) is False


# ── Property 16: OA 提交失败状态标记 ──
# **Validates: Requirements 7.4**

@given(
    voucher_id=st.text(min_size=1, max_size=20),
    amount=st.integers(min_value=1, max_value=1000000),
)
@settings(max_examples=100)
@pytest.mark.asyncio
async def test_property16_submit_failure_status(voucher_id, amount):
    """Property 16: stub submit_voucher returns failure with non-empty error."""
    config = OAConfig(api_url="http://oa.internal/api", use_webhook=True)
    conn = OAConnector(config)
    result = await conn.submit_voucher({"voucher_id": voucher_id, "amount": amount})
    assert result.success is False
    assert result.error is not None and len(result.error) > 0


# ── Property 17: Webhook 状态同步 ──
# **Validates: Requirements 7.5**

@given(status=st.sampled_from(list(ApprovalStatus)))
@settings(max_examples=100)
@pytest.mark.asyncio
async def test_property17_webhook_status_sync(status):
    """Property 17: handle_webhook returns the matching ApprovalStatus from payload."""
    secret = "prop17-secret"
    config = OAConfig(webhook_secret=secret, use_webhook=True)
    conn = OAConnector(config)
    payload = {"approval_id": "AP-PROP17", "approval_status": status.value}
    sig = _sign(payload, secret)
    result = await conn.handle_webhook(payload, sig)
    assert result == status
