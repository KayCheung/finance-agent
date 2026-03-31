"""
storage/backends/base.py
存储后端抽象接口 - 定义 SessionBackend ABC
"""
from abc import ABC, abstractmethod

from agent_core.models import SessionData, SessionSummary


class SessionBackend(ABC):
    """
    会话存储后端抽象接口。
    所有存储后端（JSON 文件、YAML 文件、Redis 等）必须实现此接口。
    接口设计兼容键值存储模式，以 session_id 为 key。
    """

    @abstractmethod
    async def save(self, session: SessionData) -> None:
        """持久化会话数据。"""
        ...

    @abstractmethod
    async def load(self, session_id: str) -> SessionData | None:
        """按 session_id 加载会话，不存在时返回 None。"""
        ...

    @abstractmethod
    async def delete(self, session_id: str) -> None:
        """删除指定会话。"""
        ...

    @abstractmethod
    async def list(self) -> list[SessionSummary]:
        """列出所有会话摘要。"""
        ...

    @abstractmethod
    async def get_latest(self) -> SessionData | None:
        """获取最近活跃的会话，无会话时返回 None。"""
        ...
