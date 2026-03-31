"""
storage/backends/yaml_backend.py
YAML 文件存储后端 - 每个会话一个 .yaml 文件，以 session_id 命名
"""
import logging
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import yaml

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


class _SafeRoundtripDumper(yaml.Dumper):
    """
    自定义 YAML Dumper，对所有字符串使用双引号样式。
    这确保 YAML 特殊处理的 Unicode 字符（如 \\x85 NEL、\\u2028 LS 等）
    通过转义序列正确保留，实现完整的序列化/反序列化往返一致性。
    """
    pass


def _str_representer(dumper: _SafeRoundtripDumper, data: str) -> yaml.ScalarNode:
    """强制所有字符串使用双引号，确保特殊字符被转义保留。"""
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style='"')


def _decimal_representer(dumper: _SafeRoundtripDumper, data: Decimal) -> yaml.ScalarNode:
    return dumper.represent_scalar("tag:yaml.org,2002:str", str(data), style='"')


def _datetime_representer(dumper: _SafeRoundtripDumper, data: datetime) -> yaml.ScalarNode:
    return dumper.represent_scalar("tag:yaml.org,2002:str", data.isoformat(), style='"')


_SafeRoundtripDumper.add_representer(str, _str_representer)
_SafeRoundtripDumper.add_representer(Decimal, _decimal_representer)
_SafeRoundtripDumper.add_representer(datetime, _datetime_representer)


class YamlSessionBackend(SessionBackend):
    """
    YAML 文件存储后端。
    每个会话存储为 {storage_dir}/{session_id}.yaml。
    使用自定义 Dumper 对字符串强制双引号，确保特殊 Unicode 字符往返一致。
    """

    def __init__(self, storage_dir: str = "./sessions") -> None:
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _file_path(self, session_id: str) -> Path:
        return self.storage_dir / f"{session_id}.yaml"

    async def save(self, session: SessionData) -> None:
        """将 SessionData 序列化为 YAML 并写入文件。"""
        data = session.model_dump(mode="python")
        file_path = self._file_path(session.session_id)
        with open(file_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, Dumper=_SafeRoundtripDumper,
                      allow_unicode=True, default_flow_style=False)

    async def load(self, session_id: str) -> SessionData | None:
        """从 YAML 文件加载会话，文件不存在或解析失败返回 None。"""
        file_path = self._file_path(session_id)
        if not file_path.exists():
            return None
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if not data or not isinstance(data, dict):
                return None
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
        for file_path in self.storage_dir.glob("*.yaml"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                if not data or not isinstance(data, dict):
                    continue
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
        for file_path in self.storage_dir.glob("*.yaml"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                if not data or not isinstance(data, dict):
                    continue
                session = SessionData(**data)
                if latest is None or session.last_active > latest.last_active:
                    latest = session
            except Exception as e:
                logger.warning("Skipping corrupt session file %s: %s", file_path.name, e)
        return latest
