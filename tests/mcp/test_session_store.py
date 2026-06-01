"""Tests for per-session state management over StreamableHTTP (GH-337).

Covers:
- SessionEntry: creation, touch, is_expired
- SessionStore.get_or_create: creates new entries, returns existing
- SessionStore.get: returns None for missing, touches on hit
- SessionStore.update: merges kwargs into data
- SessionStore.remove: returns True/False, removes entry
- SessionStore.clear: removes all sessions, returns count
- SessionStore.evict_expired: removes idle sessions
- SessionStore capacity limit: evicts oldest when max reached
- Thread safety: concurrent get_or_create calls produce one entry
- Introspection: session_count, session_ids, snapshot
- Process-level singleton: get_store, set_store
- bind_to_lifecycle: store.clear() called on lifecycle.stop()
- Environment variable overrides: DEV10X_MCP_SESSION_TTL,
  DEV10X_MCP_SESSION_MAX
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dev10x.mcp.session_store import (
    SessionEntry,
    SessionStore,
    _session_max,
    _session_ttl,
    bind_to_lifecycle,
    get_store,
    set_store,
)

# ---------------------------------------------------------------------------
# Environment variable helpers
# ---------------------------------------------------------------------------


class TestSessionTtl:
    def test_default_is_3600(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DEV10X_MCP_SESSION_TTL", raising=False)
        assert _session_ttl() == 3600.0

    def test_reads_float(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEV10X_MCP_SESSION_TTL", "60.5")
        assert _session_ttl() == 60.5

    def test_invalid_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEV10X_MCP_SESSION_TTL", "not-a-number")
        assert _session_ttl() == 3600.0

    def test_empty_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEV10X_MCP_SESSION_TTL", "")
        assert _session_ttl() == 3600.0


class TestSessionMax:
    def test_default_is_1000(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DEV10X_MCP_SESSION_MAX", raising=False)
        assert _session_max() == 1000

    def test_reads_int(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEV10X_MCP_SESSION_MAX", "50")
        assert _session_max() == 50

    def test_invalid_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEV10X_MCP_SESSION_MAX", "bad")
        assert _session_max() == 1000


# ---------------------------------------------------------------------------
# SessionEntry
# ---------------------------------------------------------------------------


class TestSessionEntry:
    def test_creation_sets_timestamps(self) -> None:
        before = time.monotonic()
        entry = SessionEntry(session_id="test-abc")
        after = time.monotonic()
        assert before <= entry.created_at <= after
        assert before <= entry.last_active <= after

    def test_initial_data_is_empty(self) -> None:
        entry = SessionEntry(session_id="x")
        assert entry.data == {}

    def test_touch_refreshes_last_active(self) -> None:
        entry = SessionEntry(session_id="y")
        original = entry.last_active
        time.sleep(0.01)
        entry.touch()
        assert entry.last_active > original

    def test_is_expired_false_when_fresh(self) -> None:
        entry = SessionEntry(session_id="z")
        assert entry.is_expired(ttl=3600.0) is False

    def test_is_expired_true_when_old(self) -> None:
        entry = SessionEntry(session_id="old")
        # Backdate last_active by 10 seconds.
        entry.last_active = time.monotonic() - 10
        assert entry.is_expired(ttl=5.0) is True

    def test_is_expired_false_when_ttl_exactly_not_reached(self) -> None:
        entry = SessionEntry(session_id="edge")
        entry.last_active = time.monotonic() - 4.9
        assert entry.is_expired(ttl=5.0) is False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store() -> SessionStore:
    """Return a fresh SessionStore with a short TTL for tests."""
    return SessionStore(ttl=60.0, max_sessions=100)


# ---------------------------------------------------------------------------
# SessionStore.get_or_create
# ---------------------------------------------------------------------------


class TestGetOrCreate:
    def test_creates_new_session(self, store: SessionStore) -> None:
        entry = store.get_or_create("sess-1")
        assert entry.session_id == "sess-1"
        assert store.session_count() == 1

    def test_returns_existing_session(self, store: SessionStore) -> None:
        e1 = store.get_or_create("sess-1")
        e2 = store.get_or_create("sess-1")
        assert e1 is e2

    def test_touches_existing_session(self, store: SessionStore) -> None:
        e1 = store.get_or_create("sess-1")
        t = e1.last_active
        time.sleep(0.01)
        store.get_or_create("sess-1")
        assert e1.last_active > t

    def test_different_ids_are_independent(self, store: SessionStore) -> None:
        e1 = store.get_or_create("a")
        e2 = store.get_or_create("b")
        assert e1 is not e2
        assert store.session_count() == 2

    def test_evicts_expired_before_creating(self, store: SessionStore) -> None:
        # Create a session then expire it manually.
        store.get_or_create("expired")
        store._sessions["expired"].last_active = time.monotonic() - 9999
        store.get_or_create("new-one")
        # "expired" must have been evicted.
        assert "expired" not in store.session_ids()
        assert "new-one" in store.session_ids()


# ---------------------------------------------------------------------------
# Capacity eviction
# ---------------------------------------------------------------------------


class TestCapacityEviction:
    def test_evicts_oldest_when_full(self) -> None:
        store = SessionStore(ttl=3600.0, max_sessions=3)
        # Create 3 sessions with controlled timestamps.
        store.get_or_create("a")
        time.sleep(0.01)
        store.get_or_create("b")
        time.sleep(0.01)
        store.get_or_create("c")

        # "a" is oldest — adding "d" should evict "a".
        store.get_or_create("d")
        ids = store.session_ids()
        assert "a" not in ids
        assert "d" in ids
        assert store.session_count() == 3

    def test_does_not_evict_below_capacity(self, store: SessionStore) -> None:
        store.get_or_create("a")
        store.get_or_create("b")
        assert store.session_count() == 2


# ---------------------------------------------------------------------------
# SessionStore.get
# ---------------------------------------------------------------------------


class TestGet:
    def test_returns_none_for_missing(self, store: SessionStore) -> None:
        assert store.get("nonexistent") is None

    def test_returns_entry_on_hit(self, store: SessionStore) -> None:
        store.get_or_create("s")
        assert store.get("s") is not None

    def test_touches_entry_on_hit(self, store: SessionStore) -> None:
        entry = store.get_or_create("s")
        t = entry.last_active
        time.sleep(0.01)
        store.get("s")
        assert entry.last_active > t

    def test_does_not_create_session(self, store: SessionStore) -> None:
        store.get("new-session")
        assert store.session_count() == 0


# ---------------------------------------------------------------------------
# SessionStore.update
# ---------------------------------------------------------------------------


class TestUpdate:
    def test_merges_into_data(self, store: SessionStore) -> None:
        store.update("s", key="value", num=42)
        entry = store.get("s")
        assert entry is not None
        assert entry.data["key"] == "value"
        assert entry.data["num"] == 42

    def test_creates_session_if_missing(self, store: SessionStore) -> None:
        store.update("new", x=1)
        assert store.session_count() == 1

    def test_merges_additional_keys(self, store: SessionStore) -> None:
        store.update("s", a=1)
        store.update("s", b=2)
        entry = store.get("s")
        assert entry is not None
        assert entry.data == {"a": 1, "b": 2}

    def test_overwrites_existing_key(self, store: SessionStore) -> None:
        store.update("s", a=1)
        store.update("s", a=99)
        entry = store.get("s")
        assert entry is not None
        assert entry.data["a"] == 99


# ---------------------------------------------------------------------------
# SessionStore.remove
# ---------------------------------------------------------------------------


class TestRemove:
    def test_returns_true_when_existed(self, store: SessionStore) -> None:
        store.get_or_create("s")
        assert store.remove("s") is True

    def test_returns_false_when_missing(self, store: SessionStore) -> None:
        assert store.remove("nonexistent") is False

    def test_session_gone_after_remove(self, store: SessionStore) -> None:
        store.get_or_create("s")
        store.remove("s")
        assert store.get("s") is None
        assert store.session_count() == 0


# ---------------------------------------------------------------------------
# SessionStore.clear
# ---------------------------------------------------------------------------


class TestClear:
    def test_removes_all_sessions(self, store: SessionStore) -> None:
        store.get_or_create("a")
        store.get_or_create("b")
        count = store.clear()
        assert count == 2
        assert store.session_count() == 0

    def test_clear_on_empty_store(self, store: SessionStore) -> None:
        assert store.clear() == 0

    def test_new_sessions_can_be_created_after_clear(self, store: SessionStore) -> None:
        store.get_or_create("a")
        store.clear()
        store.get_or_create("a")
        assert store.session_count() == 1


# ---------------------------------------------------------------------------
# SessionStore.evict_expired
# ---------------------------------------------------------------------------


class TestEvictExpired:
    def test_evicts_idle_sessions(self, store: SessionStore) -> None:
        store.get_or_create("fresh")
        store.get_or_create("stale")
        store._sessions["stale"].last_active = time.monotonic() - 9999

        count = store.evict_expired()
        assert count == 1
        assert store.get("stale") is None
        assert store.get("fresh") is not None

    def test_returns_zero_when_nothing_expired(self, store: SessionStore) -> None:
        store.get_or_create("s")
        assert store.evict_expired() == 0

    def test_returns_zero_on_empty_store(self, store: SessionStore) -> None:
        assert store.evict_expired() == 0


# ---------------------------------------------------------------------------
# Introspection
# ---------------------------------------------------------------------------


class TestIntrospection:
    def test_session_count_is_accurate(self, store: SessionStore) -> None:
        assert store.session_count() == 0
        store.get_or_create("a")
        assert store.session_count() == 1

    def test_session_ids_returns_snapshot(self, store: SessionStore) -> None:
        store.get_or_create("a")
        store.get_or_create("b")
        ids = store.session_ids()
        assert set(ids) == {"a", "b"}

    def test_snapshot_returns_copy(self, store: SessionStore) -> None:
        store.update("s", x=1)
        snap = store.snapshot("s")
        assert snap == {"x": 1}
        # Mutating the snapshot must not affect the entry.
        assert snap is not None
        snap["y"] = 2
        assert store.snapshot("s") == {"x": 1}

    def test_snapshot_returns_none_for_missing(self, store: SessionStore) -> None:
        assert store.snapshot("nonexistent") is None


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_get_or_create_produces_one_entry(self, store: SessionStore) -> None:
        results: list[SessionEntry] = []

        def worker() -> None:
            results.append(store.get_or_create("shared"))

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All threads must have received the same object.
        assert all(r is results[0] for r in results)
        assert store.session_count() == 1

    def test_concurrent_updates_are_safe(self, store: SessionStore) -> None:
        store.get_or_create("s")
        errors: list[Exception] = []

        def updater(key: str) -> None:
            try:
                for i in range(50):
                    store.update("s", **{key: i})
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=updater, args=(f"k{i}",)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []


# ---------------------------------------------------------------------------
# Process-level singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_get_store_returns_session_store(self) -> None:
        s = get_store()
        assert isinstance(s, SessionStore)

    def test_set_store_replaces_singleton(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fresh = SessionStore(ttl=10.0, max_sessions=5)
        monkeypatch.setattr("dev10x.mcp.session_store._store", fresh)
        assert get_store() is fresh

    def test_set_store_function(self, monkeypatch: pytest.MonkeyPatch) -> None:
        original = get_store()
        fresh = SessionStore()
        set_store(fresh)
        assert get_store() is fresh
        # Restore original to not leak state between tests.
        set_store(original)


# ---------------------------------------------------------------------------
# bind_to_lifecycle
# ---------------------------------------------------------------------------


class TestBindToLifecycle:
    def test_clear_called_on_stop(self, store: SessionStore) -> None:
        store.get_or_create("s")
        lifecycle = MagicMock()
        lifecycle.stop = MagicMock()
        bind_to_lifecycle(store, lifecycle)

        lifecycle.stop()
        assert store.session_count() == 0

    def test_original_stop_also_called(self, store: SessionStore) -> None:
        lifecycle = MagicMock()
        original_stop = MagicMock()
        lifecycle.stop = original_stop
        bind_to_lifecycle(store, lifecycle)

        lifecycle.stop("arg", kwarg="value")
        original_stop.assert_called_once_with("arg", kwarg="value")

    def test_multiple_binds_chain_correctly(self, store: SessionStore) -> None:
        """Binding twice chains both clear() calls (belt-and-suspenders)."""
        store2 = SessionStore(ttl=60.0, max_sessions=10)
        store.get_or_create("a")
        store2.get_or_create("b")

        lifecycle = MagicMock()
        lifecycle.stop = MagicMock()
        bind_to_lifecycle(store, lifecycle)
        bind_to_lifecycle(store2, lifecycle)

        lifecycle.stop()
        assert store.session_count() == 0
        assert store2.session_count() == 0

    def test_bind_with_real_daemon_lifecycle(self, tmp_path: Path) -> None:
        """Integration: bind_to_lifecycle clears sessions when DaemonLifecycle stops."""
        from dev10x.mcp.daemon import DaemonLifecycle

        pid_dir = tmp_path / "mcp"
        pid_dir.mkdir()

        local_store = SessionStore(ttl=3600.0, max_sessions=10)
        local_store.get_or_create("test-session")
        assert local_store.session_count() == 1

        lifecycle = DaemonLifecycle(pid_dir)
        bind_to_lifecycle(local_store, lifecycle)

        lifecycle.start()
        try:
            assert local_store.session_count() == 1  # not cleared on start
        finally:
            lifecycle.stop()

        # After stop, the session store must have been cleared.
        assert local_store.session_count() == 0
