"""
tools/account_classifier.py
科目匹配模块 - 三策略降级链（RAG → LLM → Keyword）

支持通过 strategy_chain 配置匹配策略的优先级和降级顺序。
当高优先级策略失败或置信度不足时，自动按链顺序降级到下一策略。
Keyword 策略作为兜底，始终可用。
"""
import logging
from agent_core.models import ClassifyStrategy, ClassifyResult
from rag.engine import RAGEngine

logger = logging.getLogger(__name__)

# ── 关键词规则映射表 ──
# 每条规则: (关键词列表, 科目代码, 科目名称)
_KEYWORD_RULES: list[tuple[list[str], str, str]] = [
    (["差旅", "交通", "火车", "机票", "高铁", "出租", "打车", "滴滴"], "6601.02", "差旅费"),
    (["办公", "文具", "打印"], "6601.01", "办公费"),
    (["餐饮", "餐费", "聚餐"], "6601.08", "业务招待费"),
    (["通讯", "电话", "网络"], "6601.07", "通讯费"),
]

_DEFAULT_ACCOUNT_CODE = "6601.99"
_DEFAULT_ACCOUNT_NAME = "其他费用"


class AccountClassifier:
    """
    会计科目匹配器，支持三策略降级链。

    策略链按配置顺序依次尝试：
    - RAG: 向量检索候选科目，最高相似度 < threshold 则降级
    - LLM: 通过 MCP 获取科目列表 + LLM 推理，失败则降级
    - Keyword: 硬编码关键词规则兜底，始终返回有效结果
    """

    def __init__(
        self,
        strategy_chain: list[ClassifyStrategy],
        rag_engine: RAGEngine | None = None,
        confidence_threshold: float = 0.7,
    ):
        self._strategy_chain = strategy_chain
        self._rag_engine = rag_engine
        self._confidence_threshold = confidence_threshold

    async def classify(self, ticket_type: str, usage: str) -> ClassifyResult:
        """
        按 strategy_chain 顺序尝试匹配科目。

        Args:
            ticket_type: 票据类型描述。
            usage: 费用用途描述。

        Returns:
            ClassifyResult，包含匹配的科目代码、名称、使用的策略、置信度和降级路径。
        """
        description = f"{ticket_type} {usage}".strip()
        fallback_path: list[ClassifyStrategy] = []

        strategy_methods = {
            ClassifyStrategy.RAG: self._classify_rag,
            ClassifyStrategy.LLM: self._classify_llm,
            ClassifyStrategy.KEYWORD: self._classify_keyword,
        }

        for strategy in self._strategy_chain:
            method = strategy_methods.get(strategy)
            if method is None:
                logger.warning("未知策略: %s，跳过", strategy)
                continue

            try:
                result = await method(description)
            except Exception:
                logger.exception("策略 %s 执行异常，降级到下一策略", strategy.value)
                fallback_path.append(strategy)
                continue

            if result is not None:
                result.fallback_path = fallback_path
                return result

            # result is None means strategy couldn't produce a confident answer
            fallback_path.append(strategy)
            logger.info("策略 %s 未返回有效结果，降级到下一策略", strategy.value)

        # All strategies exhausted — keyword is always the final fallback
        logger.warning("所有策略均未返回结果，使用 keyword 兜底")
        result = await self._classify_keyword(description)
        result.fallback_path = fallback_path
        return result

    async def _classify_rag(self, description: str) -> ClassifyResult | None:
        """
        RAG 策略：检索前 3 候选科目，最高相似度 < threshold 则返回 None 触发降级。
        """
        if self._rag_engine is None or not self._rag_engine.enabled:
            logger.info("RAG 引擎未启用，跳过 RAG 策略")
            return None

        candidates = await self._rag_engine.search(query=description, top_k=3)

        if not candidates:
            logger.info("RAG 检索无候选结果")
            return None

        best = max(candidates, key=lambda c: c.get("score", 0.0))
        score = best.get("score", 0.0)

        if score < self._confidence_threshold:
            logger.info(
                "RAG 最高相似度 %.3f < 阈值 %.3f，降级",
                score,
                self._confidence_threshold,
            )
            return None

        return ClassifyResult(
            account_code=best["account_code"],
            account_name=best["account_name"],
            strategy_used=ClassifyStrategy.RAG,
            confidence=score,
        )

    async def _classify_llm(self, description: str) -> ClassifyResult | None:
        """
        LLM 策略：通过 MCP 获取科目列表 + LLM 推理匹配。

        当前为 stub 实现，可通过 mock 注入测试。
        实际实现需要：
        1. 通过 MCP 接口获取企业完整科目列表
        2. 将费用描述和科目列表交给 LLM 推理
        3. 验证 LLM 返回的科目在列表中
        """
        # Stub: 返回 None 触发降级到下一策略
        logger.info("LLM 策略（stub）：未实现，降级到下一策略")
        return None

    async def _classify_keyword(self, description: str) -> ClassifyResult:
        """
        Keyword 策略：硬编码关键词规则兜底，始终返回有效结果。
        """
        for keywords, code, name in _KEYWORD_RULES:
            for kw in keywords:
                if kw in description:
                    return ClassifyResult(
                        account_code=code,
                        account_name=name,
                        strategy_used=ClassifyStrategy.KEYWORD,
                        confidence=1.0,
                    )

        return ClassifyResult(
            account_code=_DEFAULT_ACCOUNT_CODE,
            account_name=_DEFAULT_ACCOUNT_NAME,
            strategy_used=ClassifyStrategy.KEYWORD,
            confidence=0.5,
        )
