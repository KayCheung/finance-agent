"""
rag/engine.py
RAG 检索增强生成引擎 - 科目知识库检索

提供科目匹配的向量检索能力，支持通过配置启用/禁用。
当前为接口骨架，实际向量检索逻辑可后续迭代。
"""
import logging
from agent_core.config import RAGConfig

logger = logging.getLogger(__name__)


class RAGEngine:
    """
    RAG 检索引擎，用于从科目知识库中检索与费用描述最相关的候选科目。

    支持通过配置启用/禁用：
    - enabled=True: 执行向量检索，返回候选科目列表 + 相似度分数
    - enabled=False: search 直接返回空列表，Account_Classifier 自动跳过 RAG 策略
    """

    def __init__(self, config: RAGConfig | None = None, enabled: bool = False):
        """
        初始化 RAG 引擎。

        Args:
            config: RAG 配置，包含知识库目录、embedding 模型等参数。
                    若提供 config，enabled 以 config.enabled 为准。
            enabled: 是否启用 RAG 引擎（仅在 config 未提供时生效）。
        """
        if config is not None:
            self._config = config
            self._enabled = config.enabled
        else:
            self._config = RAGConfig(enabled=enabled)
            self._enabled = enabled

        if self._enabled:
            logger.info(
                "RAG 引擎已启用 (knowledge_base_dir=%s, embedding_model=%s, top_k=%d)",
                self._config.knowledge_base_dir,
                self._config.embedding_model,
                self._config.top_k,
            )
        else:
            logger.info("RAG 引擎已禁用，search 调用将返回空列表")

    @property
    def enabled(self) -> bool:
        """RAG 引擎是否启用。"""
        return self._enabled

    @property
    def config(self) -> RAGConfig:
        """当前 RAG 配置。"""
        return self._config

    async def search(self, query: str, top_k: int | None = None) -> list[dict]:
        """
        检索与查询描述最相关的候选科目。

        Args:
            query: 费用描述文本（如 "出差北京高铁票"）。
            top_k: 返回候选数量，默认使用配置中的 top_k 值。

        Returns:
            候选科目列表，每项包含:
            - account_code: 科目代码（如 "6601.02"）
            - account_name: 科目名称（如 "差旅费"）
            - score: 相似度分数（0.0 ~ 1.0）

            禁用时返回空列表。
        """
        if not self._enabled:
            return []

        if top_k is None:
            top_k = self._config.top_k

        # TODO: 实际向量检索逻辑待后续迭代实现
        # 1. 将 query 通过 embedding 模型转为向量
        # 2. 在科目知识库中进行相似度检索
        # 3. 返回 top_k 个最相关的候选科目
        logger.debug("RAG search: query=%r, top_k=%d (骨架实现，返回空列表)", query, top_k)
        return []
