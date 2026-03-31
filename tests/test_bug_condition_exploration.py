"""
tests/test_bug_condition_exploration.py
Bug Condition Exploration Tests — 验证四个缺陷在未修复代码上的存在性

Spec: image-upload-ocr-fix
Property 1: Bug Condition - 图片上传 base64 直拼 prompt 及工具注册不完整

These tests encode the EXPECTED (correct) behavior.
On UNFIXED code, they MUST FAIL — failure confirms the bug exists.
After the fix, they MUST PASS — passing confirms the bug is fixed.

**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6**
"""
import asyncio
import base64
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

# Generate random base64-encoded image data (simulating real invoice images)
_image_base64_strategy = st.binary(min_size=100, max_size=500).map(
    lambda b: base64.b64encode(b).decode("ascii")
)

_filename_strategy = st.sampled_from([
    "invoice.png", "receipt.jpg", "fapiao.pdf", "scan_001.png",
])

_message_strategy = st.sampled_from([
    "帮我报销这张发票",
    "请识别这张发票",
    "报销申请",
    "",
])


# ── Test 1a: prompt 中不应包含完整 base64 字符串 ──


class TestBugCondition1a_Base64NotInPrompt:
    """
    Test 1a: 构造包含图片的 AgentRequest（含 base64 数据），Mock Agent SDK，
    调用 _process_request，断言构建的 prompt 中不包含完整 base64 字符串。

    isBugCondition: request.images IS NOT EMPTY AND base64DataInPrompt(request)

    On UNFIXED code: FAILS (prompt contains base64 data)
    After fix: PASSES (prompt contains OCR text, not base64)

    **Validates: Requirements 1.1, 1.3**
    """

    @given(
        image_b64=_image_base64_strategy,
        filename=_filename_strategy,
        message=_message_strategy,
    )
    @settings(max_examples=20, suppress_health_check=[HealthCheck.too_slow])
    def test_prompt_should_not_contain_base64_data(
        self, image_b64: str, filename: str, message: str
    ):
        """
        For any AgentRequest with images, the prompt built by _process_request
        should NOT contain the full base64 string. Instead, it should contain
        OCR-recognized text.

        **Validates: Requirements 1.1, 1.3**
        """
        config = AgentConfig()
        core = AgentCore(mode=AgentMode.STANDALONE, config=config)

        request = AgentRequest(
            intent="invoice_reimbursement",
            message=message,
            images=[{"image_base64": image_b64, "filename": filename}],
        )

        # We need to capture the prompt that _process_request builds.
        # Mock the SDK client to capture the prompt passed to client.query()
        captured_prompts = []

        mock_client = MagicMock()
        mock_client.connect = AsyncMock()
        mock_client.query = AsyncMock()
        mock_client.receive_messages = AsyncMock(return_value=AsyncMock(
            __aiter__=lambda self: self,
            __anext__=AsyncMock(side_effect=StopAsyncIteration),
        ))

        # Make receive_messages return an async iterator that yields nothing
        async def empty_messages():
            return
            yield  # make it an async generator

        mock_client.receive_messages = empty_messages

        # Capture the prompt passed to query()
        async def capture_query(prompt, **kwargs):
            captured_prompts.append(prompt)

        mock_client.query = capture_query

        # Mock OCRService.recognize on the core instance so it doesn't
        # actually call cloud/local OCR (which requires aiohttp)
        mock_ocr_result = MagicMock(
            raw_text="发票号码: 12345\n金额: 100.00",
            mode_used="remote",
            elapsed_ms=200,
            char_count=20,
        )
        mock_recognize = AsyncMock(return_value=mock_ocr_result)

        async def run():
            with patch.object(core, "_get_or_create_sdk_client", return_value=mock_client), \
                 patch.object(core._ocr_service, "recognize", mock_recognize):
                try:
                    await core._process_request(request, {}, None)
                except Exception:
                    pass  # We only care about the prompt

            # The prompt should have been captured
            assert len(captured_prompts) > 0, "No prompt was captured from _process_request"

            prompt = captured_prompts[0]

            # EXPECTED BEHAVIOR: prompt should NOT contain the full base64 string
            # On unfixed code, the full base64 IS in the prompt → this assertion FAILS
            assert image_b64 not in prompt, (
                f"Bug confirmed: prompt contains full base64 data "
                f"(length={len(image_b64)}). "
                f"Prompt length: {len(prompt)}. "
                f"Expected: OCR text in prompt, not raw base64."
            )

        asyncio.run(run())


# ── Test 1b: OCRService.recognize 应被调用 ──


class TestBugCondition1b_OCRServiceCalled:
    """
    Test 1b: Mock OCRService.recognize，验证上传图片时该方法被调用。

    isBugCondition: ocrServiceNotCalled(input)

    On UNFIXED code: FAILS (OCRService.recognize is never called)
    After fix: PASSES (OCRService.recognize is called for each image)

    **Validates: Requirements 1.2**
    """

    @given(
        image_b64=_image_base64_strategy,
        filename=_filename_strategy,
    )
    @settings(max_examples=20, suppress_health_check=[HealthCheck.too_slow])
    def test_ocr_service_should_be_called_for_images(
        self, image_b64: str, filename: str
    ):
        """
        For any AgentRequest with images, _process_request should call
        OCRService.recognize() to perform OCR before building the prompt.

        **Validates: Requirements 1.2**
        """
        config = AgentConfig()
        core = AgentCore(mode=AgentMode.STANDALONE, config=config)

        request = AgentRequest(
            intent="invoice_reimbursement",
            message="帮我报销这张发票",
            images=[{"image_base64": image_b64, "filename": filename}],
        )

        # Mock the SDK client to avoid real API calls
        mock_client = MagicMock()
        mock_client.connect = AsyncMock()
        mock_client.query = AsyncMock()

        async def empty_messages():
            return
            yield

        mock_client.receive_messages = empty_messages

        # Mock OCRService.recognize to track if it's called
        mock_recognize = AsyncMock(return_value=MagicMock(
            raw_text="发票号码: 12345\n金额: 100.00",
            mode_used="remote",
            elapsed_ms=200,
            char_count=20,
        ))

        async def run():
            with patch.object(core, "_get_or_create_sdk_client", return_value=mock_client), \
                 patch("tools.ocr_service.OCRService.recognize", mock_recognize):
                try:
                    await core._process_request(request, {}, None)
                except Exception:
                    pass

            # EXPECTED BEHAVIOR: OCRService.recognize should have been called
            # On unfixed code, it's never called → this assertion FAILS
            assert mock_recognize.call_count > 0, (
                "Bug confirmed: OCRService.recognize was NOT called when "
                "processing an image upload. Expected at least 1 call."
            )

        asyncio.run(run())


# ── Test 1c: ocr_invoice 工具应委托 OCRService，不使用 requests.post ──


class TestBugCondition1c_OcrInvoiceDelegatesOCRService:
    """
    Test 1c: 验证 ocr_invoice 工具内部不使用 requests.post，
    而是委托 OCRService.recognize()。

    On UNFIXED code: FAILS (ocr_invoice uses requests.post directly)
    After fix: PASSES (ocr_invoice delegates to OCRService.recognize)

    **Validates: Requirements 1.4**
    """

    def test_ocr_invoice_should_not_use_requests_post(self):
        """
        The ocr_invoice tool function should NOT contain direct calls to
        requests.post. It should delegate to OCRService.recognize() instead.

        We read the _tools.py source file and check the ocr_invoice function body.

        **Validates: Requirements 1.4**
        """
        import pathlib

        tools_source = pathlib.Path("agent_core/_tools.py").read_text(encoding="utf-8")

        # Extract the ocr_invoice function body (from its definition to the next tool)
        # Find the section between "async def ocr_invoice" and the next @tool or def
        import re
        match = re.search(
            r"(async def ocr_invoice\(.*?\n)(.*?)(?=\n@tool|\ndef |\nasync def |\nclass |\Z)",
            tools_source,
            re.DOTALL,
        )
        assert match is not None, "Could not find ocr_invoice function in _tools.py"
        ocr_invoice_body = match.group(0)

        # EXPECTED BEHAVIOR: ocr_invoice body should NOT contain requests.post
        # On unfixed code, it DOES contain requests.post → this assertion FAILS
        assert "requests.post" not in ocr_invoice_body, (
            "Bug confirmed: ocr_invoice tool directly uses requests.post "
            "instead of delegating to OCRService.recognize(). "
            "This bypasses dual-mode switching, auto-fallback, and intranet validation."
        )


# ── Test 1d: allowed_tools 应包含 tax_calculate ──


class TestBugCondition1d_AllowedToolsIncludesTaxCalculate:
    """
    Test 1d: 验证 _create_sdk_client 的 allowed_tools 包含
    mcp__finance-tools__tax_calculate。

    On UNFIXED code: FAILS (allowed_tools missing tax_calculate)
    After fix: PASSES (allowed_tools includes tax_calculate)

    **Validates: Requirements 1.5**
    """

    def test_allowed_tools_should_include_tax_calculate(self):
        """
        The _create_sdk_client method should configure allowed_tools to include
        mcp__finance-tools__tax_calculate so the Agent can call the tax
        calculation tool.

        **Validates: Requirements 1.5**
        """
        config = AgentConfig()
        core = AgentCore(mode=AgentMode.STANDALONE, config=config)

        # Capture the ClaudeAgentOptions passed to ClaudeSDKClient
        captured_options = []

        original_init = None

        with patch("agent_core.core.ClaudeSDKClient") as MockClient, \
             patch("agent_core.core.create_sdk_mcp_server") as MockMCPServer:
            MockMCPServer.return_value = MagicMock()

            def capture_init(options=None, **kwargs):
                if options is not None:
                    captured_options.append(options)
                return MagicMock()

            MockClient.side_effect = capture_init

            core._create_sdk_client()

        assert len(captured_options) > 0, "ClaudeSDKClient was not created"

        options = captured_options[0]
        allowed_tools = options.allowed_tools

        # EXPECTED BEHAVIOR: allowed_tools should include tax_calculate
        # On unfixed code, it's missing → this assertion FAILS
        assert "mcp__finance-tools__tax_calculate" in allowed_tools, (
            f"Bug confirmed: allowed_tools does not include "
            f"'mcp__finance-tools__tax_calculate'. "
            f"Current allowed_tools: {allowed_tools}"
        )


# ── Test 1e: get_sdk_tools() 应包含 tax_calculate ──


class TestBugCondition1e_GetSdkToolsIncludesTaxCalculate:
    """
    Test 1e: 验证 get_sdk_tools() 返回列表包含名为 tax_calculate 的工具函数。

    On UNFIXED code: FAILS (get_sdk_tools missing tax_calculate)
    After fix: PASSES (get_sdk_tools includes tax_calculate)

    **Validates: Requirements 1.6**
    """

    def test_get_sdk_tools_should_include_tax_calculate(self):
        """
        get_sdk_tools() should return a list that includes a tool function
        named 'tax_calculate', so it can be registered to the MCP Server.

        **Validates: Requirements 1.6**
        """
        from agent_core._tools import get_sdk_tools

        tools = get_sdk_tools()
        tool_names = []
        for t in tools:
            # The @tool decorator creates SdkMcpTool objects with a .name attribute
            name = getattr(t, "name", None) or getattr(t, "__name__", None) or str(t)
            tool_names.append(name)

        # EXPECTED BEHAVIOR: tool_names should include 'tax_calculate'
        # On unfixed code, it's missing → this assertion FAILS
        assert "tax_calculate" in tool_names, (
            f"Bug confirmed: get_sdk_tools() does not include 'tax_calculate'. "
            f"Current tools: {tool_names}"
        )
