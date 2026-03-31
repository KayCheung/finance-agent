from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_core.models import SubmitResult
from extensions.submission_gateway import OASubmissionGateway, create_submission_gateway


@pytest.mark.asyncio
async def test_oa_submission_gateway_delegates_to_connector():
    connector = MagicMock()
    connector.submit_voucher = AsyncMock(return_value=SubmitResult(success=True, approval_id="AP-1"))
    gateway = OASubmissionGateway(connector=connector)

    result = await gateway.submit_voucher({"voucher_id": "V1"})
    assert gateway.channel == "oa"
    assert result.success is True
    assert result.approval_id == "AP-1"
    connector.submit_voucher.assert_called_once()


def test_create_submission_gateway_oa():
    connector = MagicMock()
    gateway = create_submission_gateway(channel="oa", oa_connector=connector)
    assert gateway is not None
    assert gateway.channel == "oa"


def test_create_submission_gateway_unsupported_returns_none():
    gateway = create_submission_gateway(channel="accounting", oa_connector=None)
    assert gateway is None
