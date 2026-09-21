"""GH-1421: a notification lost overnight must be findable in the morning."""

from __future__ import annotations

import json

import pytest

from dev10x.domain.dead_letter import (
    _MAX_RECORDED_BODY,
    dead_letter_path,
    record_undelivered,
)
from dev10x.domain.dev10x_paths import Dev10xConfigDir


@pytest.fixture(autouse=True)
def config_home(tmp_path, monkeypatch):
    monkeypatch.setenv("DEV10X_CONFIG_HOME", str(tmp_path))
    Dev10xConfigDir.reset_cache()
    yield tmp_path
    Dev10xConfigDir.reset_cache()


def _records(path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


class TestRecordUndelivered:
    def test_writes_a_findable_record(self, config_home) -> None:
        record_undelivered(
            channel="#crew",
            transport="slack",
            error="Slack API unreachable",
            body="crew stalled on worktree 7",
        )

        written = _records(dead_letter_path())
        assert len(written) == 1
        assert written[0]["channel"] == "#crew"
        assert written[0]["transport"] == "slack"
        assert written[0]["error"] == "Slack API unreachable"
        assert written[0]["body"] == "crew stalled on worktree 7"
        assert written[0]["at"]

    def test_context_is_merged_into_the_record(self, config_home) -> None:
        record_undelivered(
            channel="#crew",
            transport="pr_notify",
            error="boom",
            context={"pr_number": 42, "repo": "o/r"},
        )

        assert _records(dead_letter_path())[0]["pr_number"] == 42

    def test_records_accumulate_rather_than_overwrite(self, config_home) -> None:
        record_undelivered(channel="#a", transport="slack", error="one")
        record_undelivered(channel="#b", transport="slack", error="two")

        assert [r["error"] for r in _records(dead_letter_path())] == ["one", "two"]

    def test_a_long_body_is_truncated(self, config_home) -> None:
        """A record past PIPE_BUF loses the append's atomicity guarantee."""
        record_undelivered(channel="#a", transport="slack", error="boom", body="x" * 5000)

        assert len(_records(dead_letter_path())[0]["body"]) == _MAX_RECORDED_BODY

    def test_a_missing_body_records_as_empty(self, config_home) -> None:
        record_undelivered(channel="#a", transport="slack", error="boom")

        assert _records(dead_letter_path())[0]["body"] == ""

    def test_an_unwritable_sink_does_not_raise(self, monkeypatch) -> None:
        """The notification already failed; losing the call too is worse."""
        import dev10x.domain.dead_letter as mod

        def explode(path, line):
            raise OSError("read-only filesystem")

        monkeypatch.setattr(mod, "atomic_append_line", explode)

        record_undelivered(channel="#a", transport="slack", error="boom")

    def test_an_unserializable_context_does_not_raise(self, config_home) -> None:
        record_undelivered(
            channel="#a",
            transport="slack",
            error="boom",
            context={"handle": object()},
        )
