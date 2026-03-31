"""
tests/test_rag_engine.py
RAG 引擎单元测试
"""
import pytest
import pytest_asyncio
from rag.engine import RAGEngine
from agent_core.config import RAGConfig


class TestRAGEngineDisabled:
    """RAG 引擎禁用时的行为测试"""

    def test_disabled_by_default(self):
        engine = RAGEngine()
        assert engine.enabled is False

    def test_disabled_via_config(self):
        config = RAGConfig(enabled=False)
        engine = RAGEngine(config=config)
        assert engine.enabled is False

    def test_disabled_via_flag(self):
        engine = RAGEngine(enabled=False)
        assert engine.enabled is False

    @pytest.mark.asyncio
    async def test_search_returns_empty_when_disabled(self):
        engine = RAGEngine(enabled=False)
        result = await engine.search("出差北京高铁票")
        assert result == []

    @pytest.mark.asyncio
    async def test_search_returns_empty_when_disabled_via_config(self):
        config = RAGConfig(enabled=False)
        engine = RAGEngine(config=config)
        result = await engine.search("办公用品采购", top_k=5)
        assert result == []


class TestRAGEngineEnabled:
    """RAG 引擎启用时的行为测试（骨架实现返回空列表）"""

    def test_enabled_via_config(self):
        config = RAGConfig(enabled=True)
        engine = RAGEngine(config=config)
        assert engine.enabled is True

    def test_enabled_via_flag(self):
        engine = RAGEngine(enabled=True)
        assert engine.enabled is True

    @pytest.mark.asyncio
    async def test_search_returns_list(self):
        config = RAGConfig(enabled=True)
        engine = RAGEngine(config=config)
        result = await engine.search("差旅费报销")
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_search_with_custom_top_k(self):
        config = RAGConfig(enabled=True, top_k=5)
        engine = RAGEngine(config=config)
        result = await engine.search("交通费", top_k=10)
        assert isinstance(result, list)


class TestRAGEngineConfig:
    """RAG 引擎配置测试"""

    def test_config_priority_over_flag(self):
        """config.enabled 优先于 enabled 参数"""
        config = RAGConfig(enabled=True)
        engine = RAGEngine(config=config, enabled=False)
        assert engine.enabled is True

    def test_default_config_when_no_config_provided(self):
        engine = RAGEngine(enabled=True)
        assert engine.config.top_k == 3
        assert engine.config.knowledge_base_dir == "./rag/knowledge_base"

    def test_config_values_preserved(self):
        config = RAGConfig(
            enabled=True,
            knowledge_base_dir="/custom/path",
            embedding_model="custom-model",
            top_k=10,
        )
        engine = RAGEngine(config=config)
        assert engine.config.knowledge_base_dir == "/custom/path"
        assert engine.config.embedding_model == "custom-model"
        assert engine.config.top_k == 10
