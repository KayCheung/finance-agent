"""
storage/backends/file_backend.py
JSON 文件存储后端 - 每个会话一个 .json 文件，以 session_id 命名
"""
import json
import logging
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from agent_core.models import SessionData, SessionSummary
from storage.backends.base import SessionBackend

logger = logging.getLogger(__name__)


def _extract_session_title(session: SessionData) -> str:
    meta_title = str((session.metadata or {}).get("title") or "").strip()
    if meta_title:
        return meta_title
    for msg in session.messages:
        if not isinstance(msg, dict):
            continue
        if msg.get("role") == "user":
            content = str(msg.get("content") or "").strip()
            if content:
                return content[:24]
    return "新会话"


def _extract_session_preview(session: SessionData) -> str:
    for msg in reversed(session.messages):
        if not isinstance(msg, dict):
            continue
        content = str(msg.get("content") or "").strip()
        if content:
            return content.replace("\n", " ")[:80]
    return ""


class _SessionEncoder(json.JSONEncoder):
    """自定义 JSON 编码器，处理 Decimal 和 datetime 序列化。"""

    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


def _session_object_hook(obj: dict) -> dict:
    """JSON 解码钩子：不做自动类型转换，由 Pydantic 处理。"""
    return obj


class FileSessionBackend(SessionBackend):
    """
    JSON 文件存储后端。
    每个会话存储为 {storage_dir}/{session_id}.json。
    """

    def __init__(self, storage_dir: str = "./sessions") -> None:
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _file_path(self, session_id: str) -> Path:
        return self.storage_dir / f"{session_id}.json"

    async def save(self, session: SessionData) -> None:
        """将 SessionData 序列化为 JSON 并写入文件。"""
        data = session.model_dump(mode="python")
        file_path = self._file_path(session.session_id)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, cls=_SessionEncoder, ensure_ascii=False, indent=2)

    async def load(self, session_id: str) -> SessionData | None:
        """从 JSON 文件加载会话，文件不存在或解析失败返回 None。"""
        file_path = self._file_path(session_id)
        if not file_path.exists():
            return None
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f, object_hook=_session_object_hook)
            return SessionData(**data)
        except Exception as e:
            logger.error("Failed to load session %s: %s", session_id, e)
            return None

    async def delete(self, session_id: str) -> None:
        """删除会话文件。"""
        file_path = self._file_path(session_id)
        if file_path.exists():
            os.remove(file_path)

    async def list(self) -> list[SessionSummary]:
        """扫描目录，返回所有会话摘要列表。"""
        summaries: list[SessionSummary] = []
        for file_path in self.storage_dir.glob("*.json"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f, object_hook=_session_object_hook)
                session = SessionData(**data)
                summaries.append(
                    SessionSummary(
                        session_id=session.session_id,
                        created_at=session.created_at,
                        last_active=session.last_active,
                        voucher_count=sum(
                            1 for msg in session.messages
                            if isinstance(msg, dict) and msg.get("voucher")
                        ),
                        message_count=len(session.messages),
                        title=_extract_session_title(session),
                        preview=_extract_session_preview(session),
                        pinned=bool((session.metadata or {}).get("pinned", False)),
                        archived=bool((session.metadata or {}).get("archived", False)),
                    )
                )
            except Exception as e:
                logger.warning("Skipping corrupt session file %s: %s", file_path.name, e)
        return summaries

    async def get_latest(self) -> SessionData | None:
        """返回 last_active 最新的会话，无会话时返回 None。"""
        latest: SessionData | None = None
        for file_path in self.storage_dir.glob("*.json"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f, object_hook=_session_object_hook)
                session = SessionData(**data)
                if latest is None or session.last_active > latest.last_active:
                    latest = session
            except Exception as e:
                logger.warning("Skipping corrupt session file %s: %s", file_path.name, e)
        return latest
