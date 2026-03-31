"""
tests/test_agent_core.py
Agent_Core 的属性测试和单元测试

Feature: finance-agent-architecture-upgrade
"""
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from agent_core.config import AgentConfig
from agent_core.core import (
    AgentCore,
    _extract_ticket_amount_overrides,
    _resolve_amount_total_from_cache,
)
from agent_core.models import (
    AgentAction,
    AgentMode,
    AgentRequest,
    AgentResponse,
    CapabilityDeclaration,
    UserIdentity,
)


# ── Auto-mock LLM calls in all tests ──

@pytest.fixture(autouse=True)
def mock_llm():
    """Mock _process_request to avoid real SDK calls in tests."""
    async def fake_process(self, request, session_context, user_identity):
        return AgentResponse(success=True, reply="测试回复", action=AgentAction.NONE)

    with patch.object(AgentCore, "_process_request", fake_process):
        yield


# ── Hypothesis 自定义策略 ──

# Generate random UserIdentity
user_identity_strategy = st.builds(
    UserIdentity,
    user_id=st.text(
        alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_-"),
        min_size=1,
        max_size=20,
    ),
    department=st.text(
        alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_-"),
        min_size=1,
        max_size=20,
    ),
    role=st.sampled_from(["admin", "user", "manager", "finance", "auditor"]),
)

# Generate random session_context dicts
session_context_strategy = st.dictionaries(
    keys=st.text(
        alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_"),
        min_size=1,
        max_size=10,
    ),
    values=st.one_of(
        st.text(min_size=0, max_size=50),
        st.integers(min_value=0, max_value=10000),
        st.booleans(),
    ),
    min_size=1,
    max_size=5,
)


# ── Property 25: 嵌入模式外部上下文传递 ──
# Feature: finance-agent-architecture-upgrade, Property 25: 嵌入模式外部上下文传递


class TestProperty25EmbeddedModeExternalContext:
    """
    Property 25: 嵌入模式外部上下文传递

    For any 包含 session_context 和 user_identity 的 AgentRequest，
    Agent_Core 在嵌入模式下必须使用外部传入的上下文和身份信息，
    而非依赖内部会话管理。

    **Validates: Requirements 12.4, 12.8**
    """

    @given(
        user_identity=user_identity_strategy,
        session_context=session_context_strategy,
        intent=st.sampled_from([
            "invoice_reimbursement",
            "voucher_query",
            "batch_reimbursement",
        ]),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_embedded_mode_uses_external_context(
        self,
        user_identity: UserIdentity,
        session_context: dict,
        intent: str,
    ):
        """
        验证嵌入模式下 AgentCore 使用外部传入的 session_context 和 user_identity，
        而非内部会话管理。

        **Validates: Requirements 12.4, 12.8**
        """
        config = AgentConfig(mode="embedded")
        core = AgentCore(mode=AgentMode.EMBEDDED, config=config)

        request = AgentRequest(
            intent=intent,
            session_context=session_context,
            user_identity=user_identity,
        )

        # Verify _resolve_context returns external context
        resolved_ctx, resolved_identity = core._resolve_context(request)

        # Must use external session_context
        assert resolved_ctx == session_context, (
            f"Embedded mode should use external session_context, "
            f"got {resolved_ctx} instead of {session_context}"
        )

        # Must use external user_identity
        assert resolved_identity is not None, (
            "Embedded mode should use external user_identity, got None"
        )
        assert resolved_identity.user_id == user_identity.user_id
        assert resolved_identity.department == user_identity.department
        assert resolved_identity.role == user_identity.role

    @given(
        user_identity=user_identity_strategy,
        session_context=session_context_strategy,
        intent=st.sampled_from([
            "invoice_reimbursement",
            "voucher_query",
            "batch_reimbursement",
        ]),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_embedded_mode_invoke_returns_success(
        self,
        user_identity: UserIdentity,
        session_context: dict,
        intent: str,
    ):
        """
        验证嵌入模式下 invoke 正常返回 AgentResponse。

        **Validates: Requirements 12.4, 12.8**
        """
        config = AgentConfig(mode="embedded")
        core = AgentCore(mode=AgentMode.EMBEDDED, config=config)

        request = AgentRequest(
            intent=intent,
            session_context=session_context,
            user_identity=user_identity,
        )

        response = await core.invoke(request)

        assert isinstance(response, AgentResponse)
        assert response.success is True

    @given(
        user_identity=user_identity_strategy,
        intent=st.sampled_from([
            "invoice_reimbursement",
            "voucher_query",
            "batch_reimbursement",
        ]),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_standalone_mode_uses_internal_session(
        self,
        user_identity: UserIdentity,
        intent: str,
    ):
        """
        验证独立模式下 AgentCore 使用内部会话管理，
        不依赖外部 session_context。

        **Validates: Requirements 12.4, 12.8**
        """
        config = AgentConfig(mode="standalone")
        core = AgentCore(mode=AgentMode.STANDALONE, config=config)

        external_context = {"external_key": "external_value"}
        request = AgentRequest(
            intent=intent,
            session_id="test-session-123",
            session_context=external_context,
            user_identity=user_identity,
        )

        resolved_ctx, _ = core._resolve_context(request)

        # Standalone mode should use internal session, not external context
        assert resolved_ctx != external_context or "session_id" in resolved_ctx, (
            "Standalone mode should use internal session management"
        )
        assert "session_id" in resolved_ctx


# ── 单元测试：Agent_Core 能力声明与模式切换 ──
# Feature: finance-agent-architecture-upgrade, Task 15.4


class TestAgentCoreCapabilityDeclaration:
    """
    Agent_Core 能力声明单元测试。
    测试能力声明包含所有必需字段。

    **Validates: Requirements 12.3**
    """

    def test_capability_declaration_has_required_fields(self):
        """能力声明必须包含 agent_name、description、supported_intents、input_schema、output_schema"""
        config = AgentConfig()
        core = AgentCore(mode=AgentMode.STANDALONE, config=config)
        cap = core.get_capability()

        assert isinstance(cap, CapabilityDeclaration)
        assert cap.agent_name == "finance-reimbursement-agent"
        assert cap.description == "企业财务报销智能代理"
        assert isinstance(cap.supported_intents, list)
        assert len(cap.supported_intents) > 0
        assert isinstance(cap.input_schema, dict)
        assert isinstance(cap.output_schema, dict)

    def test_capability_supported_intents(self):
        """能力声明必须包含三种支持的意图"""
        config = AgentConfig()
        core = AgentCore(mode=AgentMode.STANDALONE, config=config)
        cap = core.get_capability()

        expected_intents = [
            "invoice_reimbursement",
            "voucher_query",
            "batch_reimbursement",
        ]
        for intent in expected_intents:
            assert intent in cap.supported_intents, (
                f"Missing intent: {intent}"
            )

    def test_capability_input_output_schemas_are_valid(self):
        """input_schema 和 output_schema 应为有效的 JSON Schema"""
        config = AgentConfig()
        core = AgentCore(mode=AgentMode.STANDALONE, config=config)
        cap = core.get_capability()

        # Schemas should be non-empty dicts (Pydantic JSON schema)
        assert len(cap.input_schema) > 0, "input_schema should not be empty"
        assert len(cap.output_schema) > 0, "output_schema should not be empty"
        # Should contain standard JSON Schema keys
        assert "properties" in cap.input_schema or "title" in cap.input_schema
        assert "properties" in cap.output_schema or "title" in cap.output_schema


class TestAgentCoreMCPToolRegistration:
    """
    嵌入模式 MCP 工具注册测试。

    **Validates: Requirements 12.5, 12.6**
    """

    def test_embedded_mode_registers_mcp_tools(self):
        """嵌入模式下 register_mcp_tools 返回工具列表"""
        config = AgentConfig(mode="embedded")
        core = AgentCore(mode=AgentMode.EMBEDDED, config=config)
        tools = core.register_mcp_tools()

        assert isinstance(tools, list)
        assert len(tools) > 0

        # Each tool should have name, description, input_schema
        for tool in tools:
            assert "name" in tool, f"Tool missing 'name': {tool}"
            assert "description" in tool, f"Tool missing 'description': {tool}"
            assert "input_schema" in tool, f"Tool missing 'input_schema': {tool}"

    def test_embedded_mode_registers_expected_tools(self):
        """嵌入模式下注册的工具应包含核心工具"""
        config = AgentConfig(mode="embedded")
        core = AgentCore(mode=AgentMode.EMBEDDED, config=config)
        tools = core.register_mcp_tools()

        tool_names = [t["name"] for t in tools]
        expected_tools = [
            "ocr_invoice",
            "classify_account",
            "generate_mcp_voucher",
            "tax_calculate",
        ]
        for expected in expected_tools:
            assert expected in tool_names, (
                f"Expected MCP tool '{expected}' not found in {tool_names}"
            )

    def test_standalone_mode_returns_empty_mcp_tools(self):
        """独立模式下 register_mcp_tools 返回空列表"""
        config = AgentConfig(mode="standalone")
        core = AgentCore(mode=AgentMode.STANDALONE, config=config)
        tools = core.register_mcp_tools()

        assert isinstance(tools, list)
        assert len(tools) == 0


class TestAgentCoreModeSwitching:
    """
    独立模式与嵌入模式切换测试。

    **Validates: Requirements 12.5, 12.6**
    """

    def test_mode_switching(self):
        """AgentCore 支持模式切换"""
        config = AgentConfig()
        core = AgentCore(mode=AgentMode.STANDALONE, config=config)

        assert core.mode == AgentMode.STANDALONE

        core.mode = AgentMode.EMBEDDED
        assert core.mode == AgentMode.EMBEDDED

        # After switching to embedded, MCP tools should be available
        tools = core.register_mcp_tools()
        assert len(tools) > 0

    def test_mode_switching_back_to_standalone(self):
        """切换回独立模式后 MCP 工具不可用"""
        config = AgentConfig()
        core = AgentCore(mode=AgentMode.EMBEDDED, config=config)

        # Embedded mode has tools
        tools = core.register_mcp_tools()
        assert len(tools) > 0

        # Switch to standalone
        core.mode = AgentMode.STANDALONE
        tools = core.register_mcp_tools()
        assert len(tools) == 0

    @pytest.mark.asyncio
    async def test_standalone_invoke(self):
        """独立模式下 invoke 正常工作"""
        config = AgentConfig(mode="standalone")
        core = AgentCore(mode=AgentMode.STANDALONE, config=config)

        request = AgentRequest(
            intent="invoice_reimbursement",
            session_id="test-session",
        )
        response = await core.invoke(request)

        assert isinstance(response, AgentResponse)
        assert response.success is True

    @pytest.mark.asyncio
    async def test_embedded_invoke(self):
        """嵌入模式下 invoke 正常工作"""
        config = AgentConfig(mode="embedded")
        core = AgentCore(mode=AgentMode.EMBEDDED, config=config)

        request = AgentRequest(
            intent="voucher_query",
            session_context={"key": "value"},
            user_identity=UserIdentity(
                user_id="u001",
                department="finance",
                role="manager",
            ),
        )
        response = await core.invoke(request)

        assert isinstance(response, AgentResponse)
        assert response.success is True


class TestAgentCoreEventCallbacks:
    """
    事件回调接口测试。

    **Validates: Requirements 12.7**
    """

    def test_event_callbacks_default_none(self):
        """事件回调默认为 None"""
        config = AgentConfig()
        core = AgentCore(mode=AgentMode.STANDALONE, config=config)

        assert core.on_voucher_created is None
        assert core.on_voucher_confirmed is None
        assert core.on_voucher_submitted is None

    def test_event_callbacks_can_be_set(self):
        """事件回调可以设置"""
        config = AgentConfig()
        core = AgentCore(mode=AgentMode.STANDALONE, config=config)

        created_events = []
        confirmed_events = []
        submitted_events = []

        core.on_voucher_created = lambda data: created_events.append(data)
        core.on_voucher_confirmed = lambda data: confirmed_events.append(data)
        core.on_voucher_submitted = lambda data: submitted_events.append(data)

        assert core.on_voucher_created is not None
        assert core.on_voucher_confirmed is not None
        assert core.on_voucher_submitted is not None

    @pytest.mark.asyncio
    async def test_fire_event_calls_callback(self):
        """_fire_event 触发已注册的回调"""
        config = AgentConfig()
        core = AgentCore(mode=AgentMode.STANDALONE, config=config)

        events = []
        core.on_voucher_created = lambda data: events.append(data)

        await core._fire_event("on_voucher_created", {"voucher_id": "VOU-001"})

        assert len(events) == 1
        assert events[0]["voucher_id"] == "VOU-001"

    @pytest.mark.asyncio
    async def test_fire_event_no_callback_no_error(self):
        """未注册回调时 _fire_event 不报错"""
        config = AgentConfig()
        core = AgentCore(mode=AgentMode.STANDALONE, config=config)

        # Should not raise
        await core._fire_event("on_voucher_created", {"voucher_id": "VOU-001"})


class TestAmountOverrides:
    def test_extract_ticket_amount_overrides(self):
        text = "的士票金额为10元，机票706.00元，火车票194.50元"
        got = _extract_ticket_amount_overrides(text)
        assert str(got.get("taxi")) == "10.00"
        assert str(got.get("air")) == "706.00"
        assert str(got.get("rail")) == "194.50"

    def test_resolve_amount_total_from_cache_with_override(self):
        cache = {
            "items": [
                {"filename": "客运汽车票3.jpg", "category": "bus", "amount": 15},
                {"filename": "的士票2.jpg", "category": "taxi", "amount": 0},
                {"filename": "机票4.png", "category": "air", "amount": 706},
                {"filename": "火车票.jpg", "category": "rail", "amount": 194.5},
            ],
            "overrides": {"taxi": 10},
        }
        got = _resolve_amount_total_from_cache(cache)
        assert str(got) == "925.50"
