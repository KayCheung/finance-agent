"""
tests/test_session_store.py
会话存储层的属性测试和单元测试
"""
import asyncio
import json
import os
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from agent_core.models import SessionData, SessionSummary
from storage.backends.base import SessionBackend
from storage.backends.file_backend import FileSessionBackend
from storage.backends.yaml_backend import YamlSessionBackend
from storage.session_store import SessionStore


# ── Hypothesis 自定义策略 ──

# 生成合法的 session_id（UUID 格式的简化版，避免文件名问题）
session_id_strategy = st.text(
    alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789"),
    min_size=8,
    max_size=32,
)

# 生成 datetime（限制范围避免序列化边界问题）
datetime_strategy = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2030, 12, 31),
)

# 生成简单的 message dict
message_strategy = st.fixed_dictionaries({
    "role": st.sampled_from(["user", "assistant"]),
    "content": st.text(min_size=1, max_size=100),
})

# 生成 metadata dict（简单键值对）
metadata_strategy = st.dictionaries(
    keys=st.text(min_size=1, max_size=20, alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz_")),
    values=st.one_of(st.text(max_size=50), st.integers(min_value=-1000, max_value=1000), st.booleans()),
    max_size=5,
)

# 生成完整的 SessionData
session_data_strategy = st.builds(
    SessionData,
    session_id=session_id_strategy,
    created_at=datetime_strategy,
    last_active=datetime_strategy,
    messages=st.lists(message_strategy, max_size=5),
    voucher_state=st.one_of(st.none(), st.fixed_dictionaries({
        "status": st.sampled_from(["draft", "confirmed", "submitted"]),
    })),
    metadata=metadata_strategy,
)


# ── Property 4: 会话存储往返一致性 ──
# Feature: finance-agent-architecture-upgrade, Property 4: 会话存储往返一致性
# **Validates: Requirements 3.4, 3.5, 3.6, 8.4**


@pytest.mark.asyncio
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(session=session_data_strategy)
async def test_property4_file_backend_roundtrip(tmp_path, session: SessionData):
    """
    Property 4: 会话存储往返一致性 (FileSessionBackend)
    For any valid SessionData, save → load should return equivalent data.
    """
    backend = FileSessionBackend(storage_dir=str(tmp_path))
    await backend.save(session)
    loaded = await backend.load(session.session_id)

    assert loaded is not None
    assert loaded.session_id == session.session_id
    assert loaded.created_at == session.created_at
    assert loaded.last_active == session.last_active
    assert loaded.messages == session.messages
    assert loaded.voucher_state == session.voucher_state
    assert loaded.metadata == session.metadata


@pytest.mark.asyncio
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(session=session_data_strategy)
async def test_property4_yaml_backend_roundtrip(tmp_path, session: SessionData):
    """
    Property 4: 会话存储往返一致性 (YamlSessionBackend)
    For any valid SessionData, save → load should return equivalent data.
    """
    backend = YamlSessionBackend(storage_dir=str(tmp_path))
    await backend.save(session)
    loaded = await backend.load(session.session_id)

    assert loaded is not None
    assert loaded.session_id == session.session_id
    assert loaded.created_at == session.created_at
    assert loaded.last_active == session.last_active
    assert loaded.messages == session.messages
    assert loaded.voucher_state == session.voucher_state
    assert loaded.metadata == session.metadata


# ── Property 5: get_latest 返回最近活跃会话 ──
# Feature: finance-agent-architecture-upgrade, Property 5: get_latest 返回最近活跃会话
# **Validates: Requirements 3.7, 8.3**


# Strategy: generate a list of sessions with unique IDs and distinct last_active timestamps
def _sessions_with_distinct_times(min_count: int = 2, max_count: int = 8):
    """Generate a list of SessionData with unique session_ids and distinct last_active."""
    return st.integers(min_value=min_count, max_value=max_count).flatmap(
        lambda n: st.lists(
            st.tuples(session_id_strategy, datetime_strategy),
            min_size=n,
            max_size=n,
            unique_by=lambda t: t[0],  # unique session_ids
        ).filter(
            lambda pairs: len({t[1] for t in pairs}) == len(pairs)  # distinct last_active
        ).map(
            lambda pairs: [
                SessionData(
                    session_id=sid,
                    created_at=datetime(2020, 1, 1),
                    last_active=la,
                )
                for sid, la in pairs
            ]
        )
    )


@pytest.mark.asyncio
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(sessions=_sessions_with_distinct_times())
async def test_property5_file_backend_get_latest(tmp_path, sessions: list[SessionData]):
    """
    Property 5: get_latest 返回最近活跃会话 (FileSessionBackend)
    For any set of sessions, get_latest returns the one with the most recent last_active.
    """
    import tempfile
    with tempfile.TemporaryDirectory(dir=str(tmp_path)) as sub_dir:
        backend = FileSessionBackend(storage_dir=sub_dir)
        for s in sessions:
            await backend.save(s)

        latest = await backend.get_latest()
        assert latest is not None

        expected = max(sessions, key=lambda s: s.last_active)
        assert latest.session_id == expected.session_id
        assert latest.last_active == expected.last_active


@pytest.mark.asyncio
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(sessions=_sessions_with_distinct_times())
async def test_property5_yaml_backend_get_latest(tmp_path, sessions: list[SessionData]):
    """
    Property 5: get_latest 返回最近活跃会话 (YamlSessionBackend)
    For any set of sessions, get_latest returns the one with the most recent last_active.
    """
    import tempfile
    with tempfile.TemporaryDirectory(dir=str(tmp_path)) as sub_dir:
        backend = YamlSessionBackend(storage_dir=sub_dir)
        for s in sessions:
            await backend.save(s)

        latest = await backend.get_latest()
        assert latest is not None

        expected = max(sessions, key=lambda s: s.last_active)
        assert latest.session_id == expected.session_id
        assert latest.last_active == expected.last_active


# ── Property 6: 会话删除后不可加载 ──
# Feature: finance-agent-architecture-upgrade, Property 6: 会话删除后不可加载
# **Validates: Requirements 3.9**


@pytest.mark.asyncio
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(session=session_data_strategy)
async def test_property6_file_backend_delete_then_load(tmp_path, session: SessionData):
    """
    Property 6: 会话删除后不可加载 (FileSessionBackend)
    Save a session, delete it, load should return None.
    """
    import tempfile
    with tempfile.TemporaryDirectory(dir=str(tmp_path)) as sub_dir:
        backend = FileSessionBackend(storage_dir=sub_dir)
        await backend.save(session)

        # Verify it was saved
        loaded = await backend.load(session.session_id)
        assert loaded is not None

        # Delete and verify
        await backend.delete(session.session_id)
        loaded_after_delete = await backend.load(session.session_id)
        assert loaded_after_delete is None


@pytest.mark.asyncio
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(session=session_data_strategy)
async def test_property6_yaml_backend_delete_then_load(tmp_path, session: SessionData):
    """
    Property 6: 会话删除后不可加载 (YamlSessionBackend)
    Save a session, delete it, load should return None.
    """
    import tempfile
    with tempfile.TemporaryDirectory(dir=str(tmp_path)) as sub_dir:
        backend = YamlSessionBackend(storage_dir=sub_dir)
        await backend.save(session)

        # Verify it was saved
        loaded = await backend.load(session.session_id)
        assert loaded is not None

        # Delete and verify
        await backend.delete(session.session_id)
        loaded_after_delete = await backend.load(session.session_id)
        assert loaded_after_delete is None


# ── 单元测试：Session_Store 边界情况 ──
# 需求: 3.8


class TestSessionStoreEdgeCases:
    """Session_Store 边界情况单元测试。"""

    @pytest.mark.asyncio
    async def test_corrupt_session_file_recovery(self, tmp_path):
        """会话数据损坏时，get_or_create 应创建新会话并设置 recovery_occurred 标志。"""
        # Write a corrupt JSON file
        corrupt_file = tmp_path / "corrupt-session.json"
        corrupt_file.write_text("{invalid json content!!!", encoding="utf-8")

        backend = FileSessionBackend(storage_dir=str(tmp_path))
        store = SessionStore(backend)

        session = await store.get_or_create(session_id="corrupt-session")
        assert session is not None
        assert session.session_id != "corrupt-session"  # New session created
        assert store.recovery_occurred is True

    @pytest.mark.asyncio
    async def test_get_latest_on_empty_storage(self, tmp_path):
        """空存储时 get_latest 返回 None，get_or_create 创建新会话。"""
        backend = FileSessionBackend(storage_dir=str(tmp_path))
        store = SessionStore(backend)

        # get_latest directly
        latest = await backend.get_latest()
        assert latest is None

        # get_or_create without session_id should create new
        session = await store.get_or_create()
        assert session is not None
        assert session.session_id  # Has a valid ID
        assert len(session.messages) == 0

    @pytest.mark.asyncio
    async def test_get_or_create_with_nonexistent_session_id(self, tmp_path):
        """指定不存在的 session_id 时，创建新会话并设置 recovery_occurred。"""
        backend = FileSessionBackend(storage_dir=str(tmp_path))
        store = SessionStore(backend)

        session = await store.get_or_create(session_id="nonexistent-id")
        assert session is not None
        assert session.session_id != "nonexistent-id"
        assert store.recovery_occurred is True

    @pytest.mark.asyncio
    async def test_get_or_create_loads_existing_session(self, tmp_path):
        """指定存在的 session_id 时，正确加载已有会话。"""
        backend = FileSessionBackend(storage_dir=str(tmp_path))
        store = SessionStore(backend)

        # Create and save a session
        original = SessionData(
            session_id="existing-session",
            created_at=datetime(2024, 1, 1),
            last_active=datetime(2024, 6, 15),
            messages=[{"role": "user", "content": "hello"}],
        )
        await store.update(original)

        # Load it back
        loaded = await store.get_or_create(session_id="existing-session")
        assert loaded.session_id == "existing-session"
        assert loaded.messages == [{"role": "user", "content": "hello"}]
        assert store.recovery_occurred is False

    @pytest.mark.asyncio
    async def test_get_or_create_returns_latest_when_no_id(self, tmp_path):
        """未指定 session_id 时，返回最近活跃的会话。"""
        backend = FileSessionBackend(storage_dir=str(tmp_path))
        store = SessionStore(backend)

        # Save two sessions
        old_session = SessionData(
            session_id="old-session",
            created_at=datetime(2024, 1, 1),
            last_active=datetime(2024, 1, 1),
        )
        new_session = SessionData(
            session_id="new-session",
            created_at=datetime(2024, 6, 1),
            last_active=datetime(2024, 6, 15),
        )
        await store.update(old_session)
        await store.update(new_session)

        # Should return the newer session
        session = await store.get_or_create()
        assert session.session_id == "new-session"

    @pytest.mark.asyncio
    async def test_dynamic_backend_loading(self):
        """通过配置项动态加载后端类。"""
        backend = SessionStore.create_backend_from_config(
            "storage.backends.file_backend.FileSessionBackend",
            storage_dir="./test_sessions_dynamic",
        )
        assert isinstance(backend, FileSessionBackend)

        # Cleanup
        import shutil
        shutil.rmtree("./test_sessions_dynamic", ignore_errors=True)

    @pytest.mark.asyncio
    async def test_dynamic_backend_loading_yaml(self):
        """通过配置项动态加载 YAML 后端类。"""
        backend = SessionStore.create_backend_from_config(
            "storage.backends.yaml_backend.YamlSessionBackend",
            storage_dir="./test_sessions_yaml_dynamic",
        )
        assert isinstance(backend, YamlSessionBackend)

        # Cleanup
        import shutil
        shutil.rmtree("./test_sessions_yaml_dynamic", ignore_errors=True)

    @pytest.mark.asyncio
    async def test_update_and_remove(self, tmp_path):
        """测试 update 和 remove 方法。"""
        backend = FileSessionBackend(storage_dir=str(tmp_path))
        store = SessionStore(backend)

        session = SessionData(
            session_id="to-remove",
            created_at=datetime(2024, 1, 1),
            last_active=datetime(2024, 1, 1),
        )
        await store.update(session)

        # Verify saved
        loaded = await store.get_or_create(session_id="to-remove")
        assert loaded.session_id == "to-remove"

        # Remove
        await store.remove("to-remove")
        loaded_after = await backend.load("to-remove")
        assert loaded_after is None
