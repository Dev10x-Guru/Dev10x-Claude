"""Tests for atomic-write semantics in session_document.write_state (GH-240 E2/E8)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from dev10x.domain import session_document
from dev10x.domain.file_locks import atomic_write_text


class TestWriteStateIsAtomic:
    """write_state must publish via os.rename so readers never see a partial file."""

    def test_writes_state_json(self, tmp_path: Path) -> None:
        path = tmp_path / "state.json"
        state = {"session_id": "abc", "branch": "develop"}
        session_document.write_state(path=path, state=state)
        assert json.loads(path.read_text()) == state

    def test_parent_directory_chmod_0700(self, tmp_path: Path) -> None:
        path = tmp_path / "nested" / "state.json"
        session_document.write_state(path=path, state={})
        assert (path.parent.stat().st_mode & 0o777) == 0o700

    def test_crash_mid_write_leaves_original_intact(self, tmp_path: Path) -> None:
        """Simulated crash inside atomic_write_text must not corrupt the
        existing state file: the new contents become visible only via
        the final os.rename, never via partial writes to the target."""
        path = tmp_path / "state.json"
        path.write_text(json.dumps({"original": True}))

        def boom(_path: Path, _content: str) -> None:
            raise RuntimeError("simulated crash")

        with patch.object(session_document, "atomic_write_text", side_effect=boom):
            with pytest.raises(RuntimeError):
                session_document.write_state(path=path, state={"new": True})

        assert json.loads(path.read_text()) == {"original": True}

    def test_uses_atomic_write_text(self, tmp_path: Path) -> None:
        path = tmp_path / "state.json"
        with patch.object(session_document, "atomic_write_text") as mock_write:
            session_document.write_state(path=path, state={"a": 1})
        mock_write.assert_called_once()
        called_path, called_content = mock_write.call_args.args
        assert called_path == path
        assert json.loads(called_content) == {"a": 1}


class TestReadPlanSummaryHasNoHookImport:
    """D1: read_plan_summary must not lazy-import from dev10x.hooks."""

    def test_uses_domain_plan_directly(self, tmp_path: Path) -> None:
        toplevel = str(tmp_path)
        plan_dir = tmp_path / ".claude" / "session"
        plan_dir.mkdir(parents=True)
        plan_yaml = plan_dir / "plan.yaml"
        plan_yaml.write_text(
            "plan:\n  status: in_progress\ntasks:\n  - id: '1'\n    subject: hi\n"
        )

        result = session_document.read_plan_summary(toplevel=toplevel)
        assert result["plan"]["status"] == "in_progress"
        assert result["tasks"][0]["subject"] == "hi"

    def test_returns_empty_when_no_plan(self, tmp_path: Path) -> None:
        result = session_document.read_plan_summary(toplevel=str(tmp_path))
        assert result == {}

    def test_no_hooks_import_in_source(self) -> None:
        """Source must not import from dev10x.hooks — domain->hooks inversion."""
        src = Path(session_document.__file__).read_text()
        assert "from dev10x.hooks" not in src
        assert "import dev10x.hooks" not in src


class TestReadPlanIdentity:
    """ADR-0018: staleness identity comes from plan-sync, not session.yaml."""

    def _write_plan(self, *, tmp_path: Path, body: str) -> str:
        plan_dir = tmp_path / ".claude" / "session"
        plan_dir.mkdir(parents=True, exist_ok=True)
        (plan_dir / "plan.yaml").write_text(body)
        return str(tmp_path)

    def test_reads_branch_and_tickets(self, tmp_path: Path) -> None:
        toplevel = self._write_plan(
            tmp_path=tmp_path,
            body="plan:\n  branch: user/GH-1/x\n  context:\n    tickets: [GH-1, GH-2]\n",
        )
        assert session_document.read_plan_identity(toplevel=toplevel) == {
            "branch": "user/GH-1/x",
            "tickets": ["GH-1", "GH-2"],
        }

    def test_missing_plan_is_identity_less(self, tmp_path: Path) -> None:
        assert session_document.read_plan_identity(toplevel=str(tmp_path)) == {
            "branch": None,
            "tickets": [],
        }

    def test_branch_without_tickets(self, tmp_path: Path) -> None:
        toplevel = self._write_plan(tmp_path=tmp_path, body="plan:\n  branch: user/GH-9/y\n")
        assert session_document.read_plan_identity(toplevel=toplevel) == {
            "branch": "user/GH-9/y",
            "tickets": [],
        }

    def test_non_string_tickets_filtered(self, tmp_path: Path) -> None:
        toplevel = self._write_plan(
            tmp_path=tmp_path,
            body="plan:\n  context:\n    tickets: [GH-1, 3, GH-2]\n",
        )
        assert session_document.read_plan_identity(toplevel=toplevel)["tickets"] == [
            "GH-1",
            "GH-2",
        ]


class TestAtomicWriteTextRoundtrip:
    """Smoke-check: atomic helper still publishes via rename."""

    def test_no_stale_tmp_after_crash(self, tmp_path: Path) -> None:
        target = tmp_path / "out.json"
        target.write_text("original")

        with patch("dev10x.domain.file_locks.os.rename", side_effect=OSError("disk full")):
            with pytest.raises(OSError):
                atomic_write_text(target, "new")

        assert target.read_text() == "original"
        leftovers = [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
        assert leftovers == []
