"""Tests for the Dev10x MCP resource update notifications (GH-341).

Covers:
- KnowledgeResourceWatcher.scan_changes detects added, removed, and modified files
- Notification dispatch to a session on content changes vs list changes
- Polling loop disabled when interval=0
- wire_watcher_to_server registers the InitializedNotification handler
- get_watcher returns the registered watcher
- _app.py lifespan creates and cancels the watcher task
- _poll_interval reads the env var with correct fallback
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

resource_watcher = pytest.importorskip(
    "dev10x.mcp.resource_watcher",
    reason="mcp not installed",
)

KnowledgeResourceWatcher = resource_watcher.KnowledgeResourceWatcher
ResourceChanged = resource_watcher.ResourceChanged
wire_watcher_to_server = resource_watcher.wire_watcher_to_server
get_watcher = resource_watcher.get_watcher
_poll_interval = resource_watcher._poll_interval


# ── helpers ────────────────────────────────────────────────────────


def _make_root(tmp_path: Path) -> Path:
    """Create a minimal plugin-root layout under *tmp_path*."""
    # skills/work-on/references/playbook.yaml
    playbook_dir = tmp_path / "skills" / "work-on" / "references"
    playbook_dir.mkdir(parents=True)
    (playbook_dir / "playbook.yaml").write_text("defaults:\n  single: []\n")

    # .claude/rules/INDEX.md and one rule
    rules_dir = tmp_path / ".claude" / "rules"
    rules_dir.mkdir(parents=True)
    (rules_dir / "INDEX.md").write_text("# Index\n")
    (rules_dir / "essentials.md").write_text("# Essentials\n")

    # references/git-commits.md
    ref_dir = tmp_path / "references"
    ref_dir.mkdir(parents=True)
    (ref_dir / "git-commits.md").write_text("# Git commits\n")

    # SKILLS.md
    (tmp_path / "SKILLS.md").write_text("# Skills\n")

    return tmp_path


def _make_watcher(tmp_path: Path, interval: float = 0.0) -> KnowledgeResourceWatcher:
    root = _make_root(tmp_path)
    return KnowledgeResourceWatcher(plugin_root=root, poll_interval=interval)


# ── _poll_interval ─────────────────────────────────────────────────


class TestPollInterval:
    def test_default_is_five(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            result = _poll_interval()

        assert result == 5.0

    def test_reads_env_var(self) -> None:
        with patch.dict("os.environ", {"DEV10X_RESOURCE_WATCH_INTERVAL": "10"}):
            result = _poll_interval()

        assert result == 10.0

    def test_invalid_env_var_falls_back_to_default(self) -> None:
        with patch.dict("os.environ", {"DEV10X_RESOURCE_WATCH_INTERVAL": "notanumber"}):
            result = _poll_interval()

        assert result == 5.0

    def test_zero_is_accepted(self) -> None:
        with patch.dict("os.environ", {"DEV10X_RESOURCE_WATCH_INTERVAL": "0"}):
            result = _poll_interval()

        assert result == 0.0


# ── scan_changes — initial seed ────────────────────────────────────


class TestScanChangesInitialSeed:
    def test_no_changes_reported_on_first_scan_after_run_seeds(
        self,
        tmp_path: Path,
    ) -> None:
        watcher = _make_watcher(tmp_path)
        # Seed snapshot directly as run() would do
        watched = watcher._watched_files()
        watcher._snapshot = watcher._take_snapshot(watched=watched)

        changes = watcher.scan_changes()

        assert changes == []

    def test_empty_snapshot_reports_existing_files_as_added(
        self,
        tmp_path: Path,
    ) -> None:
        watcher = _make_watcher(tmp_path)
        # Don't seed — simulate first scan without pre-seeding

        changes = watcher.scan_changes()

        uris = {c.uri for c in changes}
        assert "dev10x://skills/index" in uris
        assert all(c.list_changed for c in changes)


# ── scan_changes — content modified ───────────────────────────────


class TestScanChangesModified:
    def test_detects_modified_file_as_content_change(self, tmp_path: Path) -> None:
        watcher = _make_watcher(tmp_path)
        watched = watcher._watched_files()
        watcher._snapshot = watcher._take_snapshot(watched=watched)

        skills_md = tmp_path / "SKILLS.md"
        # Force a different mtime by writing new content
        skills_md.write_text("# Updated Skills\n")
        # Manipulate snapshot mtime to guarantee difference
        watcher._snapshot[skills_md].mtime -= 1.0

        changes = watcher.scan_changes()

        uris = {c.uri for c in changes}
        assert "dev10x://skills/index" in uris
        matching = [c for c in changes if c.uri == "dev10x://skills/index"]
        assert matching[0].list_changed is False

    def test_detects_modified_rule_file(self, tmp_path: Path) -> None:
        watcher = _make_watcher(tmp_path)
        watched = watcher._watched_files()
        watcher._snapshot = watcher._take_snapshot(watched=watched)

        essentials = tmp_path / ".claude" / "rules" / "essentials.md"
        essentials.write_text("# Updated Essentials\n")
        watcher._snapshot[essentials].mtime -= 1.0

        changes = watcher.scan_changes()

        uris = {c.uri for c in changes}
        assert "dev10x://rules/essentials" in uris


# ── scan_changes — file appeared/disappeared (branch coverage) ────


class TestScanChangesAppearedDisappeared:
    def test_detects_appeared_file_in_snapshot_as_list_changed(self, tmp_path: Path) -> None:
        watcher = _make_watcher(tmp_path)
        watched = watcher._watched_files()
        watcher._snapshot = watcher._take_snapshot(watched=watched)

        # SKILLS.md is in snapshot as existing; mark it as not-existing
        # to simulate a file that was gone and came back
        skills_md = tmp_path / "SKILLS.md"
        watcher._snapshot[skills_md].exists = False
        watcher._snapshot[skills_md].mtime = 0.0

        changes = watcher.scan_changes()

        uris = {c.uri for c in changes}
        assert "dev10x://skills/index" in uris
        matching = [c for c in changes if c.uri == "dev10x://skills/index"]
        assert matching[0].list_changed is True

    def test_detects_disappeared_file_in_fixed_watched_as_list_changed(
        self, tmp_path: Path
    ) -> None:
        watcher = _make_watcher(tmp_path)
        watched = watcher._watched_files()
        watcher._snapshot = watcher._take_snapshot(watched=watched)

        # Mark SKILLS.md as existing in snapshot, but make the file not exist
        skills_md = tmp_path / "SKILLS.md"
        watcher._snapshot[skills_md].exists = True
        skills_md.unlink()

        # Because SKILLS.md is a fixed path (not dynamic glob), it stays in watched
        # even when it doesn't exist, so the disappeared branch fires
        changes = watcher.scan_changes()

        uris = {c.uri for c in changes}
        assert "dev10x://skills/index" in uris
        matching = [c for c in changes if c.uri == "dev10x://skills/index"]
        assert matching[0].list_changed is True


# ── scan_changes — file added/removed ─────────────────────────────


class TestScanChangesListChanged:
    def test_detects_new_playbook_as_list_changed(self, tmp_path: Path) -> None:
        watcher = _make_watcher(tmp_path)
        watched = watcher._watched_files()
        watcher._snapshot = watcher._take_snapshot(watched=watched)

        # Add a new skill playbook
        new_skill_dir = tmp_path / "skills" / "new-skill" / "references"
        new_skill_dir.mkdir(parents=True)
        (new_skill_dir / "playbook.yaml").write_text("defaults:\n  single: []\n")

        changes = watcher.scan_changes()

        uris = {c.uri for c in changes}
        assert "dev10x://skills/new-skill/playbook" in uris
        matching = [c for c in changes if c.uri == "dev10x://skills/new-skill/playbook"]
        assert matching[0].list_changed is True

    def test_detects_removed_rule_as_list_changed(self, tmp_path: Path) -> None:
        watcher = _make_watcher(tmp_path)
        watched = watcher._watched_files()
        watcher._snapshot = watcher._take_snapshot(watched=watched)

        essentials = tmp_path / ".claude" / "rules" / "essentials.md"
        essentials.unlink()

        changes = watcher.scan_changes()

        uris = {c.uri for c in changes}
        assert "dev10x://rules/essentials" in uris
        matching = [c for c in changes if c.uri == "dev10x://rules/essentials"]
        assert matching[0].list_changed is True

    def test_detects_new_reference_file(self, tmp_path: Path) -> None:
        watcher = _make_watcher(tmp_path)
        watched = watcher._watched_files()
        watcher._snapshot = watcher._take_snapshot(watched=watched)

        new_ref = tmp_path / "references" / "new-guide.md"
        new_ref.write_text("# New Guide\n")

        changes = watcher.scan_changes()

        uris = {c.uri for c in changes}
        assert "dev10x://references/new-guide" in uris


# ── scan_changes — deduplication ──────────────────────────────────


class TestScanChangesDeduplication:
    def test_same_uri_reported_once_per_scan(self, tmp_path: Path) -> None:
        watcher = _make_watcher(tmp_path)
        # Empty snapshot → all files appear as additions
        changes = watcher.scan_changes()

        uris = [c.uri for c in changes]
        assert len(uris) == len(set(uris)), "duplicate URIs in scan results"


# ── set_session ────────────────────────────────────────────────────


class TestSetSession:
    def test_set_session_attaches_session(self, tmp_path: Path) -> None:
        watcher = _make_watcher(tmp_path)
        mock_session = MagicMock()

        watcher.set_session(session=mock_session)

        assert watcher._session is mock_session

    def test_set_session_none_detaches(self, tmp_path: Path) -> None:
        watcher = _make_watcher(tmp_path)
        watcher.set_session(session=MagicMock())

        watcher.set_session(session=None)

        assert watcher._session is None


# ── _notify ────────────────────────────────────────────────────────


class TestNotify:
    @pytest.mark.asyncio
    async def test_no_op_when_session_is_none(self, tmp_path: Path) -> None:
        watcher = _make_watcher(tmp_path)
        # session not set — should not raise

        await watcher._notify(events=[ResourceChanged(uri="dev10x://rules/index")])

    @pytest.mark.asyncio
    async def test_no_op_when_events_empty(self, tmp_path: Path) -> None:
        watcher = _make_watcher(tmp_path)
        session = AsyncMock()
        watcher.set_session(session=session)

        await watcher._notify(events=[])

        session.send_resource_list_changed.assert_not_called()
        session.send_resource_updated.assert_not_called()

    @pytest.mark.asyncio
    async def test_sends_list_changed_for_list_change_event(self, tmp_path: Path) -> None:
        watcher = _make_watcher(tmp_path)
        session = AsyncMock()
        watcher.set_session(session=session)

        await watcher._notify(
            events=[ResourceChanged(uri="dev10x://rules/essentials", list_changed=True)]
        )

        session.send_resource_list_changed.assert_called_once()
        session.send_resource_updated.assert_not_called()

    @pytest.mark.asyncio
    async def test_sends_resource_updated_for_content_change(self, tmp_path: Path) -> None:
        watcher = _make_watcher(tmp_path)
        session = AsyncMock()
        watcher.set_session(session=session)

        await watcher._notify(
            events=[ResourceChanged(uri="dev10x://skills/index", list_changed=False)]
        )

        session.send_resource_updated.assert_called_once()
        session.send_resource_list_changed.assert_not_called()

    @pytest.mark.asyncio
    async def test_sends_both_for_mixed_events(self, tmp_path: Path) -> None:
        watcher = _make_watcher(tmp_path)
        session = AsyncMock()
        watcher.set_session(session=session)

        await watcher._notify(
            events=[
                ResourceChanged(uri="dev10x://rules/new-rule", list_changed=True),
                ResourceChanged(uri="dev10x://skills/index", list_changed=False),
            ]
        )

        session.send_resource_list_changed.assert_called_once()
        session.send_resource_updated.assert_called_once()

    @pytest.mark.asyncio
    async def test_detaches_session_on_send_failure(self, tmp_path: Path) -> None:
        watcher = _make_watcher(tmp_path)
        session = AsyncMock()
        session.send_resource_list_changed.side_effect = Exception("connection lost")
        watcher.set_session(session=session)

        await watcher._notify(
            events=[ResourceChanged(uri="dev10x://rules/index", list_changed=True)]
        )

        assert watcher._session is None


# ── run loop ───────────────────────────────────────────────────────


class TestRunLoop:
    @pytest.mark.asyncio
    async def test_returns_immediately_when_interval_is_zero(self, tmp_path: Path) -> None:
        watcher = KnowledgeResourceWatcher(plugin_root=_make_root(tmp_path), poll_interval=0.0)

        # Should return without blocking
        await asyncio.wait_for(watcher.run(), timeout=1.0)

    @pytest.mark.asyncio
    async def test_seeds_snapshot_and_cancels_cleanly(self, tmp_path: Path) -> None:
        watcher = KnowledgeResourceWatcher(plugin_root=_make_root(tmp_path), poll_interval=0.05)
        task = asyncio.create_task(watcher.run())
        await asyncio.sleep(0.01)  # let it seed
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Snapshot was seeded — no spurious changes on next manual scan
        changes = watcher.scan_changes()
        assert changes == []

    @pytest.mark.asyncio
    async def test_loop_body_notifies_on_detected_change(self, tmp_path: Path) -> None:
        """Verify the loop calls _notify when scan_changes returns events."""
        watcher = KnowledgeResourceWatcher(plugin_root=_make_root(tmp_path), poll_interval=0.02)
        session = AsyncMock()
        watcher.set_session(session=session)

        task = asyncio.create_task(watcher.run())
        await asyncio.sleep(0.01)  # let it seed snapshot

        # Create a new file so the next tick detects a list change
        new_ref = tmp_path / "references" / "loop-added.md"
        new_ref.write_text("# Loop Added\n")

        # Wait long enough for a tick to scan and notify
        await asyncio.sleep(0.06)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        session.send_resource_list_changed.assert_called()

    @pytest.mark.asyncio
    async def test_loop_swallows_scan_exception(self, tmp_path: Path) -> None:
        """Verify a scan_changes exception inside the loop is caught, not fatal."""
        watcher = KnowledgeResourceWatcher(plugin_root=_make_root(tmp_path), poll_interval=0.02)

        call_count = {"n": 0}

        def _boom() -> list:
            call_count["n"] += 1
            raise RuntimeError("scan blew up")

        # Seed first, then swap in the raising scan so the loop hits the except branch
        task = asyncio.create_task(watcher.run())
        await asyncio.sleep(0.01)  # let it seed
        watcher.scan_changes = _boom  # type: ignore[method-assign]

        await asyncio.sleep(0.06)  # at least one tick raises and is swallowed
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert call_count["n"] >= 1, "the raising scan was never invoked by the loop"


# ── _snapshot_uri ─────────────────────────────────────────────────


class TestSnapshotUri:
    """Direct unit tests for the _snapshot_uri path-derivation helper."""

    def test_returns_none_for_path_outside_root(self, tmp_path: Path) -> None:
        watcher = _make_watcher(tmp_path)
        outside = Path("/completely/unrelated/path.md")

        result = watcher._snapshot_uri(path=outside)

        assert result is None

    def test_returns_skills_index_for_skills_md(self, tmp_path: Path) -> None:
        watcher = _make_watcher(tmp_path)
        skills_md = tmp_path / "SKILLS.md"

        result = watcher._snapshot_uri(path=skills_md)

        assert result == "dev10x://skills/index"

    def test_returns_reference_uri_for_references_md(self, tmp_path: Path) -> None:
        watcher = _make_watcher(tmp_path)
        ref_file = tmp_path / "references" / "git-commits.md"

        result = watcher._snapshot_uri(path=ref_file)

        assert result == "dev10x://references/git-commits"

    def test_returns_playbook_uri_for_skill_playbook_yaml(self, tmp_path: Path) -> None:
        watcher = _make_watcher(tmp_path)
        playbook = tmp_path / "skills" / "my-skill" / "references" / "playbook.yaml"

        result = watcher._snapshot_uri(path=playbook)

        assert result == "dev10x://skills/my-skill/playbook"

    def test_returns_none_for_unrecognized_path_inside_root(self, tmp_path: Path) -> None:
        watcher = _make_watcher(tmp_path)
        unrecognized = tmp_path / "some" / "other" / "file.txt"

        result = watcher._snapshot_uri(path=unrecognized)

        assert result is None

    def test_snapshot_uri_used_when_dir_removed_from_watched(self, tmp_path: Path) -> None:
        """Verify _snapshot_uri covers removed-from-watch path in scan_changes."""
        watcher = _make_watcher(tmp_path)
        watched = watcher._watched_files()
        watcher._snapshot = watcher._take_snapshot(watched=watched)

        # Simulate a path that was previously watched but is no longer watched
        # by injecting it into the snapshot directly (won't be in next _watched_files)
        phantom = tmp_path / "references" / "phantom.md"
        watcher._snapshot[phantom] = resource_watcher._FileState(exists=True, mtime=1.0)

        changes = watcher.scan_changes()

        uris = {c.uri for c in changes}
        assert "dev10x://references/phantom" in uris
        matching = [c for c in changes if c.uri == "dev10x://references/phantom"]
        assert matching[0].list_changed is True


# ── wire_watcher_to_server ─────────────────────────────────────────


class TestWireWatcherToServer:
    @pytest.mark.asyncio
    async def test_registers_initialized_notification_handler(self, tmp_path: Path) -> None:
        import mcp.types as mcp_types

        stub_server = MagicMock()
        stub_server.notification_handlers = {}

        watcher = _make_watcher(tmp_path)
        wire_watcher_to_server(server=stub_server, watcher=watcher)

        assert mcp_types.InitializedNotification in stub_server.notification_handlers

    @pytest.mark.asyncio
    async def test_handler_sets_session_from_request_context(self, tmp_path: Path) -> None:
        import mcp.types as mcp_types

        mock_session = MagicMock()
        stub_server = MagicMock()
        stub_server.notification_handlers = {}
        stub_server.request_context.session = mock_session

        watcher = _make_watcher(tmp_path)
        wire_watcher_to_server(server=stub_server, watcher=watcher)

        handler = stub_server.notification_handlers[mcp_types.InitializedNotification]
        await handler(mcp_types.InitializedNotification())

        assert watcher._session is mock_session

    @pytest.mark.asyncio
    async def test_handler_tolerates_missing_request_context(self, tmp_path: Path) -> None:
        import mcp.types as mcp_types

        stub_server = MagicMock()
        stub_server.notification_handlers = {}
        stub_server.request_context.session = None
        type(stub_server).request_context = property(
            lambda self: (_ for _ in ()).throw(LookupError("no context"))
        )

        watcher = _make_watcher(tmp_path)
        wire_watcher_to_server(server=stub_server, watcher=watcher)

        handler = stub_server.notification_handlers[mcp_types.InitializedNotification]
        # Should not raise even when request_context is unavailable
        await handler(mcp_types.InitializedNotification())

        # Session not wired — watcher still detached
        assert watcher._session is None

    def test_registers_watcher_in_global_registry(self, tmp_path: Path) -> None:
        stub_server = MagicMock()
        stub_server.notification_handlers = {}

        watcher = _make_watcher(tmp_path)
        wire_watcher_to_server(server=stub_server, watcher=watcher)

        assert get_watcher() is watcher


# ── get_watcher ────────────────────────────────────────────────────


class TestGetWatcher:
    def test_returns_none_before_registration(self) -> None:
        resource_watcher._holder.reset()

        result = get_watcher()

        assert result is None


# ── lifespan integration ───────────────────────────────────────────


class TestLifespanIntegration:
    @pytest.mark.asyncio
    async def test_lifespan_starts_and_cancels_watcher_task(self) -> None:
        from dev10x.mcp._app import _server_lifespan

        mock_app = MagicMock()
        mock_app._mcp_server.notification_handlers = {}

        # Patch at the module where the name is bound (module-level imports in _app.py)
        with patch("dev10x.mcp._app.get_plugin_root", return_value=Path("/nonexistent")):
            with patch("dev10x.mcp._app.KnowledgeResourceWatcher") as MockWatcher:
                mock_watcher_instance = MagicMock()

                async def _fake_run() -> None:
                    try:
                        await asyncio.sleep(999)
                    except asyncio.CancelledError:
                        pass

                mock_watcher_instance.run = _fake_run
                MockWatcher.return_value = mock_watcher_instance

                with patch("dev10x.mcp._app.wire_roots_to_server"):
                    async with _server_lifespan(mock_app):
                        # Lifespan is active — watcher should be running
                        pass
                # After exit — task should be cancelled (no exception raised)

    @pytest.mark.asyncio
    async def test_lifespan_wires_watcher_to_server(self) -> None:
        from dev10x.mcp._app import _server_lifespan

        mock_app = MagicMock()
        mock_app._mcp_server.notification_handlers = {}

        # Patch at the module where the name is bound (module-level imports in _app.py)
        with patch("dev10x.mcp._app.get_plugin_root", return_value=Path("/nonexistent")):
            with patch("dev10x.mcp._app.KnowledgeResourceWatcher") as MockWatcher:
                mock_watcher_instance = MagicMock()

                async def _fake_run() -> None:
                    await asyncio.sleep(0)

                mock_watcher_instance.run = _fake_run
                MockWatcher.return_value = mock_watcher_instance

                with patch("dev10x.mcp._app.wire_watcher_to_server") as mock_wire:
                    with patch("dev10x.mcp._app.wire_roots_to_server"):
                        async with _server_lifespan(mock_app):
                            pass

                mock_wire.assert_called_once_with(
                    server=mock_app._mcp_server,
                    watcher=mock_watcher_instance,
                )
