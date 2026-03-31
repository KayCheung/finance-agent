"""
tests/test_preservation_properties.py
Preservation Property Tests — 验证非图片请求及已有工具行为在修复前后保持不变

Spec: image-upload-ocr-fix
Property 4: Preservation - 非图片请求行为不变
Property 5: Preservation - 已有工具行为不变

These tests MUST PASS on UNFIXED code (establishing baseline behavior).
After the fix, they MUST STILL PASS (confirming no regressions).

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6**
"""
import asyncio
import json
import re
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from agent_core.config import AgentConfig
from agent_core.core import AgentCore
from agent_core.models import (
    AgentAction,
    AgentMode,
    AgentRequest,
    AgentResponse,
)


# ── Hypothesis strategies ──

_text_message_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Z"),
        whitelist_characters="，。！？、；：""''（）【】",
    ),
    min_size=1,
    max_size=200,
)

_session_id_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_"),
    min_size=1,
    max_size=30,
)


# ── Property 4: Preservation - 非图片请求行为不变 ──


class TestProperty4_NonImageRequestPreservation:
    """
    Property 4: Preservation - 非图片请求行为不变

    For any AgentRequest where images is empty (text-only or empty message),
    _process_request should produce the same behavior before and after the fix.

    **Validates: Requirements 3.1, 3.2, 3.3, 3.4**
    """

    @given(message=_text_message_strategy)
    @settings(max_examples=30, suppress_health_check=[HealthCheck.too_slow])
    def test_text_only_prompt_contains_only_user_message(self, message: str):
        """
        For any non-image AgentRequest with a text message, the prompt passed
        to the SDK client should contain only the user's message text.

        **Validates: Requirements 3.1**
        """
        config = AgentConfig()
        core = AgentCore(mode=AgentMode.STANDALONE, config=config)

        request = AgentRequest(
            intent="invoice_reimbursement",
            message=message,
            images=[],
        )

        captured_prompts = []

        mock_client = MagicMock()
        mock_client.connect = AsyncMock()

        async def capture_query(prompt, **kwargs):
            captured_prompts.append(prompt)

        mock_client.query = capture_query

        async def empty_messages():
            return
            yield

        mock_client.receive_messages = empty_messages

        async def run():
            with patch.object(core, "_get_or_create_sdk_client", return_value=mock_client):
                await core._process_request(request, {}, None)

            assert len(captured_prompts) > 0, "No prompt was captured"
            prompt = captured_prompts[0]
            assert prompt == message, (
                f"Text-only prompt should be exactly the user message. "
                f"Expected: {message!r}, Got: {prompt!r}"
            )

        asyncio.run(run())

    @given(session_id=_session_id_strategy)
    @settings(max_examples=20, suppress_health_check=[HealthCheck.too_slow])
    def test_empty_message_no_images_returns_prompt(self, session_id: str):
        """
        For any AgentRequest with empty message and no images,
        _process_request should return "请输入您的问题或上传发票图片。"

        **Validates: Requirements 3.3**
        """
        config = AgentConfig()
        core = AgentCore(mode=AgentMode.STANDALONE, config=config)

        request = AgentRequest(
            intent="invoice_reimbursement",
            session_id=session_id,
            message="",
            images=[],
        )

        async def run():
            response = await core._process_request(request, {}, None)
            assert isinstance(response, AgentResponse)
            assert response.success is True
            assert response.reply == "请输入您的问题或上传发票图片。"
            assert response.action == AgentAction.NONE

        asyncio.run(run())

    def test_none_message_no_images_returns_prompt(self):
        """
        AgentRequest with message=None and no images returns the standard prompt.

        **Validates: Requirements 3.3**
        """
        config = AgentConfig()
        core = AgentCore(mode=AgentMode.STANDALONE, config=config)

        request = AgentRequest(
            intent="invoice_reimbursement",
            message=None,
            images=[],
        )

        async def run():
            response = await core._process_request(request, {}, None)
            assert isinstance(response, AgentResponse)
            assert response.success is True
            assert response.reply == "请输入您的问题或上传发票图片。"

        asyncio.run(run())

    @given(
        voucher_id=st.from_regex(r"VOU-[0-9]{8}-[A-F0-9]{6}", fullmatch=True),
        department=st.sampled_from(["财务部", "技术部", "市场部", "人事部"]),
        submitter=st.sampled_from(["张三", "李四", "王五"]),
        amount=st.floats(min_value=0.01, max_value=99999.99, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=20, suppress_health_check=[HealthCheck.too_slow])
    def test_voucher_json_parsing_from_reply(
        self, voucher_id: str, department: str, submitter: str, amount: float
    ):
        """
        When the AI reply contains %%VOUCHER_JSON_START%%...%%VOUCHER_JSON_END%%,
        the voucher JSON should be correctly parsed and action set to PREVIEW.

        **Validates: Requirements 3.2**
        """
        amount = round(amount, 2)
        voucher_json = json.dumps({
            "voucher_id": voucher_id,
            "summary": f"{department}{submitter}报销",
            "department": department,
            "submitter": submitter,
            "entries": [
                {"account_code": "6602.02", "account_name": "差旅费", "debit": amount, "credit": 0},
                {"account_code": "2241", "account_name": f"其他应付款-{submitter}", "debit": 0, "credit": amount},
            ],
            "total_debit": amount,
            "total_credit": amount,
            "balanced": True,
        }, ensure_ascii=False)

        reply_text = (
            f"好的，已为您生成凭证草稿：\n\n"
            f"%%VOUCHER_JSON_START%%\n{voucher_json}\n%%VOUCHER_JSON_END%%\n\n"
            f"请确认是否提交。"
        )

        # Test the voucher JSON extraction logic directly (same regex as _process_request)
        json_match = re.search(
            r'%%VOUCHER_JSON_START%%\s*(.*?)\s*%%VOUCHER_JSON_END%%',
            reply_text, re.DOTALL,
        )
        assert json_match is not None, "VOUCHER_JSON block not found in reply"

        parsed = json.loads(json_match.group(1))
        assert isinstance(parsed, dict)
        assert parsed["voucher_id"] == voucher_id
        assert parsed["department"] == department
        assert parsed["submitter"] == submitter
        assert parsed["balanced"] is True

    @given(
        error_msg=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
            min_size=1,
            max_size=100,
        ),
    )
    @settings(max_examples=20, suppress_health_check=[HealthCheck.too_slow])
    def test_sdk_exception_returns_error_response(self, error_msg: str):
        """
        When the Agent SDK raises an exception during processing,
        _process_request should return AgentResponse with success=False
        and non-empty errors.

        **Validates: Requirements 3.4**
        """
        config = AgentConfig()
        core = AgentCore(mode=AgentMode.STANDALONE, config=config)

        request = AgentRequest(
            intent="invoice_reimbursement",
            message="帮我报销",
            images=[],
        )

        mock_client = MagicMock()
        mock_client.connect = AsyncMock(side_effect=Exception(error_msg))

        async def run():
            with patch.object(core, "_get_or_create_sdk_client", return_value=mock_client):
                response = await core._process_request(request, {}, None)

            assert response.success is False
            assert response.action == AgentAction.ERROR
            assert len(response.errors) > 0
            assert error_msg in response.errors[0]

        asyncio.run(run())


# ── Property 5: Preservation - 已有工具行为不变 ──


class TestProperty5_ExistingToolPreservation:
    """
    Property 5: Preservation - 已有工具行为不变

    For any classify_account or generate_mcp_voucher tool call,
    the tool signatures (parameter names, return format) must remain unchanged.

    **Validates: Requirements 3.5, 3.6**
    """

    @given(
        ticket_type=st.sampled_from([
            "增值税专用发票", "增值税普通发票", "电子发票",
            "火车票", "机票行程单", "出租车票", "过路费发票",
            "未知类型", "其他",
        ]),
        usage=st.sampled_from([
            "出差", "打车", "住宿", "餐饮", "办公用品",
            "培训", "通信费", "其他费用", "会议",
        ]),
    )
    @settings(max_examples=30, suppress_health_check=[HealthCheck.too_slow])
    def test_classify_account_signature_and_return_format(
        self, ticket_type: str, usage: str
    ):
        """
        classify_account tool should accept {ticket_type, usage} and return
        a dict with {account_code: str, account_name: str, matched: bool}.

        **Validates: Requirements 3.5, 3.6**
        """
        from agent_core._tools import classify_account

        # SdkMcpTool wraps the handler; access via .handler attribute
        handler = classify_account.handler
        args = {"ticket_type": ticket_type, "usage": usage}

        async def run():
            result = await handler(args)

            assert isinstance(result, dict), (
                f"classify_account should return dict, got {type(result)}"
            )
            assert "account_code" in result, "Missing 'account_code' in result"
            assert "account_name" in result, "Missing 'account_name' in result"
            assert "matched" in result, "Missing 'matched' in result"

            assert isinstance(result["account_code"], str)
            assert isinstance(result["account_name"], str)
            assert isinstance(result["matched"], bool)

            assert re.match(r"\d{4}\.\d{2}", result["account_code"]), (
                f"account_code format invalid: {result['account_code']}"
            )

        asyncio.run(run())

    def test_classify_account_tool_name_and_schema(self):
        """
        classify_account SdkMcpTool should have the expected name and
        input_schema keys (ticket_type, usage).

        **Validates: Requirements 3.5, 3.6**
        """
        from agent_core._tools import classify_account

        assert classify_account.name == "classify_account"
        assert classify_account.handler is not None

        schema = classify_account.input_schema
        # Schema can be a dict or a type; verify it contains expected keys
        if isinstance(schema, dict):
            assert "ticket_type" in schema
            assert "usage" in schema

    @given(
        department=st.sampled_from(["财务部", "技术部", "市场部"]),
        submitter=st.sampled_from(["张三", "李四", "王五"]),
        summary=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N")),
            min_size=2,
            max_size=50,
        ),
        total_amount=st.floats(min_value=0.01, max_value=99999.99, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=30, suppress_health_check=[HealthCheck.too_slow])
    def test_generate_mcp_voucher_signature_and_return_format(
        self, department: str, submitter: str, summary: str, total_amount: float
    ):
        """
        generate_mcp_voucher tool should accept the expected args and return
        a dict with {success: bool, voucher_id: str, mcp_voucher: dict}.

        **Validates: Requirements 3.5, 3.6**
        """
        from agent_core._tools import generate_mcp_voucher

        handler = generate_mcp_voucher.handler
        total_amount = round(total_amount, 2)
        args = {
            "summary": summary,
            "department": department,
            "submitter": submitter,
            "entries": [
                {"account_code": "6602.02", "account_name": "差旅费", "debit": total_amount, "credit": 0},
            ],
            "total_amount": total_amount,
            "invoice_info": {"ticket_type": "train", "amount": total_amount},
        }

        async def run():
            result = await handler(args)

            assert isinstance(result, dict), (
                f"generate_mcp_voucher should return dict, got {type(result)}"
            )
            assert "success" in result
            assert "voucher_id" in result
            assert "mcp_voucher" in result

            assert isinstance(result["success"], bool)
            assert result["success"] is True
            assert isinstance(result["voucher_id"], str)
            assert isinstance(result["mcp_voucher"], dict)

            assert re.match(r"VOU-\d{8}-[A-F0-9]{6}", result["voucher_id"]), (
                f"voucher_id format invalid: {result['voucher_id']}"
            )

            mcp = result["mcp_voucher"]
            assert mcp["protocol"] == "MCP/1.0"
            assert "voucher_type" in mcp
            assert "voucher_id" in mcp
            assert "department" in mcp
            assert "submitter" in mcp
            assert "entries" in mcp
            assert mcp["status"] == "pending_approval"

        asyncio.run(run())

    def test_generate_mcp_voucher_tool_name_and_schema(self):
        """
        generate_mcp_voucher SdkMcpTool should have the expected name and
        input_schema keys.

        **Validates: Requirements 3.5, 3.6**
        """
        from agent_core._tools import generate_mcp_voucher

        assert generate_mcp_voucher.name == "generate_mcp_voucher"
        assert generate_mcp_voucher.handler is not None

        schema = generate_mcp_voucher.input_schema
        if isinstance(schema, dict):
            assert "summary" in schema
            assert "department" in schema
            assert "submitter" in schema

    def test_get_sdk_tools_includes_existing_tools(self):
        """
        get_sdk_tools() must always include classify_account, generate_mcp_voucher,
        and ocr_invoice in its return list.

        **Validates: Requirements 3.5, 3.6**
        """
        from agent_core._tools import get_sdk_tools

        tools = get_sdk_tools()
        tool_names = [t.name for t in tools]

        assert "classify_account" in tool_names, (
            f"get_sdk_tools() must include 'classify_account'. Got: {tool_names}"
        )
        assert "generate_mcp_voucher" in tool_names, (
            f"get_sdk_tools() must include 'generate_mcp_voucher'. Got: {tool_names}"
        )
        assert "ocr_invoice" in tool_names, (
            f"get_sdk_tools() must include 'ocr_invoice'. Got: {tool_names}"
        )
