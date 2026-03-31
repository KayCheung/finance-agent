"""
tests/test_account_classifier.py
AccountClassifier 单元测试
"""
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch

from agent_core.models import ClassifyStrategy, ClassifyResult
from rag.engine import RAGEngine
from tools.account_classifier import AccountClassifier


# ── Fixtures ──

@pytest.fixture
def keyword_only_classifier():
    """仅使用 keyword 策略的分类器。"""
    return AccountClassifier(
        strategy_chain=[ClassifyStrategy.KEYWORD],
        rag_engine=None,
    )


@pytest.fixture
def full_chain_classifier():
    """完整降级链 rag→llm→keyword 的分类器。"""
    rag = RAGEngine(enabled=False)
    return AccountClassifier(
        strategy_chain=[ClassifyStrategy.RAG, ClassifyStrategy.LLM, ClassifyStrategy.KEYWORD],
        rag_engine=rag,
        confidence_threshold=0.7,
    )


# ── Keyword 策略测试 ──

class TestKeywordClassify:
    @pytest.mark.asyncio
    async def test_travel_keywords(self, keyword_only_classifier):
        """差旅相关关键词应匹配到 6601.02 差旅费。"""
        for usage in ["差旅", "交通", "火车", "机票", "高铁"]:
            result = await keyword_only_classifier.classify("", usage)
            assert result.account_code == "6601.02"
            assert result.account_name == "差旅费"
            assert result.strategy_used == ClassifyStrategy.KEYWORD

    @pytest.mark.asyncio
    async def test_taxi_keywords(self, keyword_only_classifier):
        """出租/打车/滴滴应匹配到 6601.02 差旅费。"""
        for usage in ["出租", "打车", "滴滴"]:
            result = await keyword_only_classifier.classify("", usage)
            assert result.account_code == "6601.02"
            assert result.account_name == "差旅费"

    @pytest.mark.asyncio
    async def test_office_keywords(self, keyword_only_classifier):
        """办公相关关键词应匹配到 6601.01 办公费。"""
        for usage in ["办公", "文具", "打印"]:
            result = await keyword_only_classifier.classify("", usage)
            assert result.account_code == "6601.01"
            assert result.account_name == "办公费"

    @pytest.mark.asyncio
    async def test_dining_keywords(self, keyword_only_classifier):
        """餐饮相关关键词应匹配到 6601.08 业务招待费。"""
        for usage in ["餐饮", "餐费", "聚餐"]:
            result = await keyword_only_classifier.classify("", usage)
            assert result.account_code == "6601.08"
            assert result.account_name == "业务招待费"

    @pytest.mark.asyncio
    async def test_telecom_keywords(self, keyword_only_classifier):
        """通讯相关关键词应匹配到 6601.07 通讯费。"""
        for usage in ["通讯", "电话", "网络"]:
            result = await keyword_only_classifier.classify("", usage)
            assert result.account_code == "6601.07"
            assert result.account_name == "通讯费"

    @pytest.mark.asyncio
    async def test_default_fallback(self, keyword_only_classifier):
        """无法匹配的描述应返回 6601.99 其他费用。"""
        result = await keyword_only_classifier.classify("", "未知费用类型")
        assert result.account_code == "6601.99"
        assert result.account_name == "其他费用"
        assert result.confidence == 0.5

    @pytest.mark.asyncio
    async def test_keyword_confidence_is_1(self, keyword_only_classifier):
        """关键词匹配成功时置信度应为 1.0。"""
        result = await keyword_only_classifier.classify("", "火车票报销")
        assert result.confidence == 1.0


# ── 降级链测试 ──

class TestFallbackChain:
    @pytest.mark.asyncio
    async def test_rag_disabled_falls_to_keyword(self, full_chain_classifier):
        """RAG 禁用 + LLM stub → 降级到 keyword。"""
        result = await full_chain_classifier.classify("火车票", "出差北京")
        assert result.strategy_used == ClassifyStrategy.KEYWORD
        assert ClassifyStrategy.RAG in result.fallback_path
        assert ClassifyStrategy.LLM in result.fallback_path

    @pytest.mark.asyncio
    async def test_rag_low_confidence_falls_through(self):
        """RAG 返回低置信度结果时应降级。"""
        rag = RAGEngine(enabled=True)
        rag.search = AsyncMock(return_value=[
            {"account_code": "6601.02", "account_name": "差旅费", "score": 0.3},
        ])
        classifier = AccountClassifier(
            strategy_chain=[ClassifyStrategy.RAG, ClassifyStrategy.KEYWORD],
            rag_engine=rag,
            confidence_threshold=0.7,
        )
        result = await classifier.classify("", "出差")
        assert result.strategy_used == ClassifyStrategy.KEYWORD
        assert ClassifyStrategy.RAG in result.fallback_path

    @pytest.mark.asyncio
    async def test_rag_high_confidence_returns_result(self):
        """RAG 返回高置信度结果时应直接使用。"""
        rag = RAGEngine(enabled=True)
        rag.search = AsyncMock(return_value=[
            {"account_code": "6601.02", "account_name": "差旅费", "score": 0.95},
            {"account_code": "6601.01", "account_name": "办公费", "score": 0.3},
        ])
        classifier = AccountClassifier(
            strategy_chain=[ClassifyStrategy.RAG, ClassifyStrategy.KEYWORD],
            rag_engine=rag,
            confidence_threshold=0.7,
        )
        result = await classifier.classify("火车票", "出差")
        assert result.strategy_used == ClassifyStrategy.RAG
        assert result.account_code == "6601.02"
        assert result.confidence == 0.95
        assert result.fallback_path == []

    @pytest.mark.asyncio
    async def test_rag_exception_falls_through(self):
        """RAG 抛出异常时应降级到下一策略。"""
        rag = RAGEngine(enabled=True)
        rag.search = AsyncMock(side_effect=RuntimeError("connection error"))
        classifier = AccountClassifier(
            strategy_chain=[ClassifyStrategy.RAG, ClassifyStrategy.KEYWORD],
            rag_engine=rag,
            confidence_threshold=0.7,
        )
        result = await classifier.classify("", "办公用品")
        assert result.strategy_used == ClassifyStrategy.KEYWORD
        assert ClassifyStrategy.RAG in result.fallback_path

    @pytest.mark.asyncio
    async def test_rag_empty_results_falls_through(self):
        """RAG 返回空列表时应降级。"""
        rag = RAGEngine(enabled=True)
        rag.search = AsyncMock(return_value=[])
        classifier = AccountClassifier(
            strategy_chain=[ClassifyStrategy.RAG, ClassifyStrategy.KEYWORD],
            rag_engine=rag,
            confidence_threshold=0.7,
        )
        result = await classifier.classify("", "餐费")
        assert result.strategy_used == ClassifyStrategy.KEYWORD
        assert ClassifyStrategy.RAG in result.fallback_path


# ── 结果元数据测试 ──

class TestResultMetadata:
    @pytest.mark.asyncio
    async def test_result_contains_all_fields(self, keyword_only_classifier):
        """结果应包含所有必需字段。"""
        result = await keyword_only_classifier.classify("", "火车票")
        assert isinstance(result.account_code, str)
        assert isinstance(result.account_name, str)
        assert isinstance(result.strategy_used, ClassifyStrategy)
        assert isinstance(result.confidence, float)
        assert isinstance(result.fallback_path, list)

    @pytest.mark.asyncio
    async def test_strategy_used_in_chain(self, full_chain_classifier):
        """strategy_used 应在降级链中。"""
        result = await full_chain_classifier.classify("", "打印纸")
        assert result.strategy_used in full_chain_classifier._strategy_chain

    @pytest.mark.asyncio
    async def test_description_combines_ticket_type_and_usage(self):
        """classify 应将 ticket_type 和 usage 组合为描述。"""
        classifier = AccountClassifier(
            strategy_chain=[ClassifyStrategy.KEYWORD],
        )
        # "火车" in ticket_type should trigger 差旅费
        result = await classifier.classify("火车票", "")
        assert result.account_code == "6601.02"


# ── Property 9: 科目匹配降级链 ──
# Feature: finance-agent-architecture-upgrade, Property 9: 科目匹配降级链

from hypothesis import given, settings, strategies as st


def _rag_confidence_strategy():
    """生成 RAG 候选科目的随机置信度分数 (0.0 ~ 1.0)。"""
    return st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)


def _llm_success_strategy():
    """生成 LLM 策略是否成功的随机布尔值。"""
    return st.booleans()


def _threshold_strategy():
    """生成随机置信度阈值 (0.1 ~ 0.9)。"""
    return st.floats(min_value=0.1, max_value=0.9, allow_nan=False, allow_infinity=False)


class TestProperty9FallbackChain:
    """
    **Validates: Requirements 5.5, 5.6, 5.8**

    Property 9: 科目匹配降级链
    For any 配置的策略降级链（rag→llm→keyword），当当前策略失败或置信度低于阈值时，
    Account_Classifier 必须按链顺序尝试下一策略；当所有高优先级策略不可用时，
    必须回退到 keyword 模式并返回有效结果。
    """

    @given(
        rag_confidence=_rag_confidence_strategy(),
        llm_succeeds=_llm_success_strategy(),
        threshold=_threshold_strategy(),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_fallback_chain_order_and_keyword_guarantee(
        self, rag_confidence: float, llm_succeeds: bool, threshold: float
    ):
        """
        Mock RAG/LLM returns with random confidence, verify fallback follows
        chain order and ultimately falls back to keyword with valid result.

        **Validates: Requirements 5.5, 5.6, 5.8**
        """
        # Setup RAG engine with mocked search returning random confidence
        rag = RAGEngine(enabled=True)
        rag.search = AsyncMock(return_value=[
            {"account_code": "6601.02", "account_name": "差旅费", "score": rag_confidence},
        ])

        # Setup LLM mock: either returns a result or raises an exception
        llm_result = None
        if llm_succeeds:
            llm_result = ClassifyResult(
                account_code="6601.01",
                account_name="办公费",
                strategy_used=ClassifyStrategy.LLM,
                confidence=0.85,
            )

        classifier = AccountClassifier(
            strategy_chain=[ClassifyStrategy.RAG, ClassifyStrategy.LLM, ClassifyStrategy.KEYWORD],
            rag_engine=rag,
            confidence_threshold=threshold,
        )

        # Mock _classify_llm to control LLM behavior
        if llm_succeeds:
            classifier._classify_llm = AsyncMock(return_value=llm_result)
        else:
            classifier._classify_llm = AsyncMock(return_value=None)

        result = await classifier.classify("火车票", "出差北京")

        # ── Core assertions ──

        # 1. Result is always valid (has account_code and account_name)
        assert result.account_code, "account_code must be non-empty"
        assert result.account_name, "account_name must be non-empty"
        assert isinstance(result.confidence, float)

        # 2. Determine expected behavior based on RAG confidence vs threshold
        rag_succeeds = rag_confidence >= threshold

        if rag_succeeds:
            # RAG confidence >= threshold → RAG should be used directly
            assert result.strategy_used == ClassifyStrategy.RAG
            assert ClassifyStrategy.RAG not in result.fallback_path
        elif llm_succeeds:
            # RAG failed, LLM succeeds → LLM should be used
            assert result.strategy_used == ClassifyStrategy.LLM
            assert ClassifyStrategy.RAG in result.fallback_path
            assert ClassifyStrategy.LLM not in result.fallback_path
        else:
            # Both RAG and LLM failed → must fall back to keyword
            assert result.strategy_used == ClassifyStrategy.KEYWORD
            assert ClassifyStrategy.RAG in result.fallback_path
            assert ClassifyStrategy.LLM in result.fallback_path

        # 3. fallback_path records strategies that were tried and failed,
        #    in the order they appear in the chain
        for i in range(len(result.fallback_path) - 1):
            chain = [ClassifyStrategy.RAG, ClassifyStrategy.LLM, ClassifyStrategy.KEYWORD]
            idx_a = chain.index(result.fallback_path[i])
            idx_b = chain.index(result.fallback_path[i + 1])
            assert idx_a < idx_b, (
                f"fallback_path order must follow chain order, "
                f"got {result.fallback_path}"
            )

    @given(rag_confidence=_rag_confidence_strategy())
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_keyword_always_returns_valid_result_as_final_fallback(
        self, rag_confidence: float
    ):
        """
        When all higher-priority strategies fail, keyword must always return
        a valid result with non-empty account_code and account_name.

        **Validates: Requirements 5.8**
        """
        # RAG returns low confidence, LLM fails
        rag = RAGEngine(enabled=True)
        rag.search = AsyncMock(return_value=[
            {"account_code": "6601.02", "account_name": "差旅费", "score": rag_confidence},
        ])

        classifier = AccountClassifier(
            strategy_chain=[ClassifyStrategy.RAG, ClassifyStrategy.LLM, ClassifyStrategy.KEYWORD],
            rag_engine=rag,
            confidence_threshold=1.1,  # threshold > 1.0 ensures RAG always fails
        )
        # LLM always fails
        classifier._classify_llm = AsyncMock(return_value=None)

        result = await classifier.classify("", "随机费用描述")

        # Keyword must always produce a valid result
        assert result.strategy_used == ClassifyStrategy.KEYWORD
        assert result.account_code, "keyword must return non-empty account_code"
        assert result.account_name, "keyword must return non-empty account_name"
        assert result.confidence > 0, "keyword confidence must be positive"
        # Both RAG and LLM should be in fallback_path
        assert ClassifyStrategy.RAG in result.fallback_path
        assert ClassifyStrategy.LLM in result.fallback_path

    @given(
        rag_confidence=_rag_confidence_strategy(),
        threshold=_threshold_strategy(),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_rag_below_threshold_triggers_fallback(
        self, rag_confidence: float, threshold: float
    ):
        """
        When RAG confidence < threshold, classifier must not use RAG result
        and must fall through to next strategy.

        **Validates: Requirements 5.5**
        """
        rag = RAGEngine(enabled=True)
        rag.search = AsyncMock(return_value=[
            {"account_code": "6601.02", "account_name": "差旅费", "score": rag_confidence},
        ])

        classifier = AccountClassifier(
            strategy_chain=[ClassifyStrategy.RAG, ClassifyStrategy.KEYWORD],
            rag_engine=rag,
            confidence_threshold=threshold,
        )

        result = await classifier.classify("", "出差")

        if rag_confidence < threshold:
            # RAG below threshold → should NOT use RAG
            assert result.strategy_used != ClassifyStrategy.RAG
            assert ClassifyStrategy.RAG in result.fallback_path
        else:
            # RAG above threshold → should use RAG
            assert result.strategy_used == ClassifyStrategy.RAG
            assert ClassifyStrategy.RAG not in result.fallback_path


# ── Property 10: 科目匹配结果元数据完整性 ──
# Feature: finance-agent-architecture-upgrade, Property 10: 科目匹配结果元数据完整性


def _strategy_chain_strategy():
    """
    生成随机策略链：从 [RAG, LLM] 中取子集，始终以 KEYWORD 结尾。
    可能的链: [KEYWORD], [RAG, KEYWORD], [LLM, KEYWORD], [RAG, LLM, KEYWORD]
    """
    optional = [ClassifyStrategy.RAG, ClassifyStrategy.LLM]
    return st.lists(
        st.sampled_from(optional),
        min_size=0,
        max_size=2,
        unique=True,
    ).map(lambda prefix: prefix + [ClassifyStrategy.KEYWORD])


class TestProperty10MetadataCompleteness:
    """
    **Validates: Requirements 5.7**

    Property 10: 科目匹配结果元数据完整性
    For any 科目匹配结果，必须包含 strategy_used（使用的策略）、confidence（置信度分数）
    和 fallback_path（降级路径），且 strategy_used 必须是降级链中的某个策略。
    """

    @given(
        chain=_strategy_chain_strategy(),
        rag_confidence=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        llm_succeeds=st.booleans(),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_result_metadata_fields_present(
        self,
        chain: list[ClassifyStrategy],
        rag_confidence: float,
        llm_succeeds: bool,
    ):
        """
        For any random strategy chain and RAG/LLM behavior, the classify result
        must contain strategy_used, confidence (float), and fallback_path (list).

        **Validates: Requirements 5.7**
        """
        # Setup RAG engine (enabled only if RAG is in the chain)
        rag = None
        if ClassifyStrategy.RAG in chain:
            rag = RAGEngine(enabled=True)
            rag.search = AsyncMock(return_value=[
                {"account_code": "6601.02", "account_name": "差旅费", "score": rag_confidence},
            ])

        classifier = AccountClassifier(
            strategy_chain=chain,
            rag_engine=rag,
            confidence_threshold=0.7,
        )

        # Mock LLM behavior if LLM is in the chain
        if ClassifyStrategy.LLM in chain:
            if llm_succeeds:
                classifier._classify_llm = AsyncMock(return_value=ClassifyResult(
                    account_code="6601.01",
                    account_name="办公费",
                    strategy_used=ClassifyStrategy.LLM,
                    confidence=0.85,
                ))
            else:
                classifier._classify_llm = AsyncMock(return_value=None)

        result = await classifier.classify("火车票", "出差报销")

        # ── Metadata completeness assertions ──

        # 1. strategy_used must be present and be a ClassifyStrategy
        assert hasattr(result, "strategy_used"), "result must have strategy_used"
        assert isinstance(result.strategy_used, ClassifyStrategy), (
            f"strategy_used must be ClassifyStrategy, got {type(result.strategy_used)}"
        )

        # 2. confidence must be present and be a float
        assert hasattr(result, "confidence"), "result must have confidence"
        assert isinstance(result.confidence, float), (
            f"confidence must be float, got {type(result.confidence)}"
        )

        # 3. fallback_path must be present and be a list
        assert hasattr(result, "fallback_path"), "result must have fallback_path"
        assert isinstance(result.fallback_path, list), (
            f"fallback_path must be list, got {type(result.fallback_path)}"
        )

    @given(
        chain=_strategy_chain_strategy(),
        rag_confidence=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        llm_succeeds=st.booleans(),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_strategy_used_in_chain(
        self,
        chain: list[ClassifyStrategy],
        rag_confidence: float,
        llm_succeeds: bool,
    ):
        """
        For any random strategy chain, strategy_used in the result must be
        one of the strategies present in the configured chain.

        **Validates: Requirements 5.7**
        """
        rag = None
        if ClassifyStrategy.RAG in chain:
            rag = RAGEngine(enabled=True)
            rag.search = AsyncMock(return_value=[
                {"account_code": "6601.02", "account_name": "差旅费", "score": rag_confidence},
            ])

        classifier = AccountClassifier(
            strategy_chain=chain,
            rag_engine=rag,
            confidence_threshold=0.7,
        )

        if ClassifyStrategy.LLM in chain:
            if llm_succeeds:
                classifier._classify_llm = AsyncMock(return_value=ClassifyResult(
                    account_code="6601.01",
                    account_name="办公费",
                    strategy_used=ClassifyStrategy.LLM,
                    confidence=0.85,
                ))
            else:
                classifier._classify_llm = AsyncMock(return_value=None)

        result = await classifier.classify("", "办公用品采购")

        # strategy_used must be one of the strategies in the configured chain
        assert result.strategy_used in chain, (
            f"strategy_used={result.strategy_used} not in chain={chain}"
        )

        # fallback_path entries must also be from the chain
        for s in result.fallback_path:
            assert s in chain, (
                f"fallback_path entry {s} not in chain={chain}"
            )
