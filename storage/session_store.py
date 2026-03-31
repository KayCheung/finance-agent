"""
storage/session_store.py
Session_Store 门面 - 封装 SessionBackend，提供会话管理高层接口
"""
import importlib
import logging
import uuid
from datetime import datetime

from agent_core.models import SessionData
from storage.backends.base import SessionBackend

logger = logging.getLogger(__name__)


class SessionStore:
    """
    会话存储门面。
    封装 SessionBackend 实例，提供 get_or_create / update / remove 高层操作。
    """

    def __init__(self, backend: SessionBackend) -> None:
        self._backend = backend
        self.recovery_occurred: bool = False

    async def get_or_create(self, session_id: str | None = None) -> SessionData:
        """
        获取或创建会话：
        - session_id 存在 → 从后端加载
        - session_id 为 None → 尝试 get_latest，若无则创建新会话
        - 加载失败（损坏/格式错误）→ 记录错误日志，创建新会话，设置 recovery_occurred 标志
        """
        self.recovery_occurred = False

        if session_id is not None:
            try:
                session = await self._backend.load(session_id)
                if session is not None:
                    return session
                # load returned None — session not found or corrupt
                logger.warning(
                    "Session %s not found or corrupt, creating new session", session_id
                )
                self.recovery_occurred = True
            except Exception as e:
                logger.error("Failed to load session %s: %s", session_id, e)
                self.recovery_occurred = True
            return self._create_new_session()

        # No session_id — try to get latest
        try:
            latest = await self._backend.get_latest()
            if latest is not None:
                return latest
        except Exception as e:
            logger.error("Failed to get latest session: %s", e)
            self.recovery_occurred = True

        return self._create_new_session()

    async def update(self, session: SessionData) -> None:
        """将会话状态同步写入后端。"""
        await self._backend.save(session)

    async def remove(self, session_id: str) -> None:
        """删除指定会话。"""
        await self._backend.delete(session_id)

    @staticmethod
    def _create_new_session() -> SessionData:
        """创建一个新的空会话。"""
        now = datetime.now()
        return SessionData(
            session_id=str(uuid.uuid4()),
            created_at=now,
            last_active=now,
        )

    @staticmethod
    def create_backend_from_config(
        backend_class: str, **kwargs
    ) -> SessionBackend:
        """
        通过配置项动态加载后端类。
        backend_class: 完整类路径，如 "storage.backends.file_backend.FileSessionBackend"
        kwargs: 传递给后端构造函数的参数（如 storage_dir）
        """
        module_path, class_name = backend_class.rsplit(".", 1)
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        return cls(**kwargs)
