"""Tests for artifact validation and storage (GH-1938)."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from dev10x.domain.common.result import ErrorResult, err, ok

from dev10x.comm.overwatch.artifacts import (
    CONTROL_EVENT,
    SHARE_EVENT,
    ArtifactStore,
    ArtifactSummary,
    check_value,
    find_control,
    new_event_id,
    validate_document,
)
from tests.comm.overwatch.artifact_fixtures import DOCUMENT, OWNER, document
from tests.comm.overwatch.conftest import NOW

SLUG_ERROR = "must be a slug: lowercase letters, digits and '-', up to 64"


def _set(*, target: Any, keys: list[Any], value: Any) -> Any:
    for key in keys[:-1]:
        target = target[key]
    target[keys[-1]] = value


def _ticking_clock() -> Callable[[], datetime]:
    ticks: Iterator[int] = iter(range(1000))
    return lambda: NOW + timedelta(minutes=next(ticks))


@pytest.fixture
def store(tmp_path: Path) -> ArtifactStore:
    return ArtifactStore(root=tmp_path / "artifacts", now=_ticking_clock())


@pytest.fixture
def stored(store: ArtifactStore) -> dict[str, Any]:
    saved = store.put(document=document(), owner=OWNER)
    return saved.value  # type: ignore[union-attr]


class TestValidateDocument:
    def test_accepts_every_block_type(self) -> None:
        assert validate_document(document=document()) == ok(DOCUMENT)

    def test_drops_store_managed_fields(self) -> None:
        result = validate_document(
            document=document(revision=9, updated_at="x", owner={}, shares=[])
        )

        assert result == ok(DOCUMENT)

    def test_meta_is_optional(self) -> None:
        bare = {key: value for key, value in DOCUMENT.items() if key != "meta"}

        assert validate_document(document=bare) == ok(bare)

    def test_accepts_empty_optional_text(self) -> None:
        assert validate_document(document=document(description="")) == ok(document(description=""))

    @pytest.mark.parametrize(
        ("keys", "value", "error"),
        [
            (["schema"], "v0", 'schema: must be "dev10x.artifact/v1"'),
            (["id"], "Bad Id", f"id: {SLUG_ERROR}"),
            (["id"], "trailing\n", f"id: {SLUG_ERROR}"),
            (["title"], "", "title: must be a non-empty string"),
            (["description"], 3, "description: must be a non-empty string"),
            (["meta"], [], "meta: must be an object"),
            (["meta", "as_of"], 1, "meta.as_of: must be a string"),
            (["views"], [], "views: needs at least 1 item(s)"),
            (["views"], "x", "views: must be a list"),
            (["views", 0], "x", "views[0]: must be an object"),
            (["views", 1, "id"], "summary", 'views[1].id: duplicate view id "summary"'),
            (["views", 0, "label"], "", "views[0].label: must be a non-empty string"),
            (
                ["views", 0, "blocks", 0, "type"],
                "foo",
                'views[0].blocks[0].type: unknown block type "foo"',
            ),
            (
                ["views", 0, "blocks", 0, "type"],
                3,
                'views[0].blocks[0].type: unknown block type "3"',
            ),
            (
                ["views", 0, "blocks", 1, "paragraphs"],
                [1],
                "views[0].blocks[1].paragraphs[0]: must be a string",
            ),
            (
                ["views", 0, "blocks", 2, "tone"],
                "red",
                "views[0].blocks[2].tone: must be one of ok, warn, bad, info",
            ),
            (
                ["views", 0, "blocks", 3, "items", 0],
                "x",
                "views[0].blocks[3].items[0]: must be an object",
            ),
            (
                ["views", 0, "blocks", 3, "items", 0, "key"],
                "",
                "views[0].blocks[3].items[0].key: must be a non-empty string",
            ),
            (
                ["views", 0, "blocks", 4, "columns"],
                [],
                "views[0].blocks[4].columns: needs at least 1 item(s)",
            ),
            (
                ["views", 0, "blocks", 4, "rows", 0],
                "x",
                "views[0].blocks[4].rows[0]: must be a list of cells",
            ),
            (
                ["views", 0, "blocks", 4, "rows", 0, 0],
                3,
                "views[0].blocks[4].rows[0][0]: must be an object",
            ),
            (
                ["views", 0, "blocks", 4, "rows", 0, 1, "tone"],
                "red",
                "views[0].blocks[4].rows[0][1].tone: must be one of ok, warn, bad, info",
            ),
            (
                ["views", 0, "blocks", 5, "items", 0, "tone"],
                "red",
                "views[0].blocks[5].items[0].tone: must be one of ok, warn, bad, info",
            ),
            (
                ["views", 0, "blocks", 6, "items", 0, "note"],
                1,
                "views[0].blocks[6].items[0].note: must be a non-empty string",
            ),
            (
                ["views", 0, "blocks", 7, "source"],
                "",
                "views[0].blocks[7].source: must be a non-empty string",
            ),
            (
                ["views", 0, "blocks", 8, "label"],
                "",
                "views[0].blocks[8].label: must be a non-empty string",
            ),
            (
                ["views", 0, "blocks", 9, "items", 0, "ref"],
                "",
                "views[0].blocks[9].items[0].ref: must be a non-empty string",
            ),
            (
                ["views", 0, "blocks", 10, "items"],
                "x",
                "views[0].blocks[10].items: must be a list",
            ),
            (
                ["views", 0, "blocks", 10, "items", 0, "control"],
                "nope",
                'views[0].blocks[10].items[0].control: no control with id "nope"',
            ),
            (
                ["views", 1, "blocks", 0, "tone"],
                "loud",
                "views[1].blocks[0].tone: must be one of primary, danger, default",
            ),
            (
                ["views", 1, "blocks", 0, "id"],
                "Bad",
                f"views[1].blocks[0].id: {SLUG_ERROR}",
            ),
            (
                ["views", 1, "blocks", 1, "options"],
                ["one"],
                "views[1].blocks[1].options: needs at least 2 item(s)",
            ),
            (
                ["views", 1, "blocks", 1, "id"],
                "ship",
                'views[1].blocks[1].id: duplicate control id "ship"',
            ),
            (
                ["views", 1, "blocks", 2, "multi"],
                "yes",
                "views[1].blocks[2].multi: must be true or false",
            ),
            (
                ["views", 1, "blocks", 3, "fields"],
                [],
                "views[1].blocks[3].fields: needs at least 1 item(s)",
            ),
            (
                ["views", 1, "blocks", 3, "fields", 1, "name"],
                "why",
                'views[1].blocks[3].fields[1].name: duplicate field name "why"',
            ),
            (
                ["views", 1, "blocks", 3, "fields", 0, "kind"],
                "date",
                "views[1].blocks[3].fields[0].kind: must be one of text, textarea, select",
            ),
            (
                ["views", 1, "blocks", 3, "fields", 1, "options"],
                [],
                "views[1].blocks[3].fields[1].options: needs at least 1 item(s)",
            ),
        ],
    )
    def test_error_names_the_path(self, keys: list[Any], value: Any, error: str) -> None:
        broken = document()
        _set(target=broken, keys=keys, value=value)

        assert validate_document(document=broken) == err(error)

    def test_rejects_a_non_object(self) -> None:
        assert validate_document(document=[]) == err("document: must be an object")

    def test_rejects_an_oversized_document(self) -> None:
        big = document()
        big["views"][0]["blocks"][1]["paragraphs"] = ["x" * (600 * 1024)]

        result = validate_document(document=big)

        assert isinstance(result, ErrorResult) and result.error.endswith(
            "bytes; the limit is 512 KiB"
        )


class TestControls:
    @pytest.mark.parametrize(("control_id", "found"), [("ship", "button"), ("nope", None)])
    def test_find_control(self, control_id: str, found: str | None) -> None:
        control = find_control(document=DOCUMENT, control_id=control_id) or {}

        assert control.get("type") == found

    @pytest.mark.parametrize(
        ("control_id", "value", "expected"),
        [
            ("ship", "Ship it", ok("Ship it")),
            ("ship", 1, err("A button sends a string.")),
            ("window", "Fri", ok("Fri")),
            ("window", "Sun", err("Pick from the listed options.")),
            ("window", ["Fri"], err("Pick from the listed options.")),
            ("regions", ["eu", "us"], ok(["eu", "us"])),
            ("regions", "eu", err("This choice takes a list of options.")),
            ("regions", ["xx"], err("Pick from the listed options.")),
            ("notes", {"why": "late"}, ok({"why": "late"})),
            ("notes", "late", err("A form sends an object of field values.")),
            ("notes", {"other": "x"}, err("A form sends only its own fields, each as a string.")),
            ("notes", {"why": 1}, err("A form sends only its own fields, each as a string.")),
            ("notes", {"risk": "low"}, ok({"risk": "low"})),
            ("notes", {"risk": ""}, ok({"risk": ""})),
            ("notes", {"risk": "high"}, err("Pick risk from its listed options.")),
        ],
    )
    def test_check_value(self, control_id: str, value: object, expected: object) -> None:
        control = find_control(document=DOCUMENT, control_id=control_id)

        assert check_value(control=control or {}, value=value) == expected

    def test_event_ids_are_unique(self) -> None:
        assert new_event_id() != new_event_id()


class TestPut:
    def test_first_put_is_revision_one(self, stored: dict[str, Any]) -> None:
        assert (
            stored["revision"],
            stored["updated_at"],
            stored["owner"],
            stored["shares"],
        ) == (1, NOW.isoformat(timespec="seconds"), OWNER, [])

    def test_writes_the_document(self, store: ArtifactStore, stored: dict[str, Any]) -> None:
        assert store.get(artifact_id="rollout-review") == stored

    def test_next_put_bumps_revision_and_keeps_shares(
        self, store: ArtifactStore, stored: dict[str, Any]
    ) -> None:
        store.add_share(artifact_id="rollout-review", publisher="claude-ai", url="https://a")
        newer = {"session_id": "s2", "name": "n2", "cwd": "/n"}

        saved = store.put(document=document(title="Again"), owner=newer).value  # type: ignore[union-attr]

        assert (saved["revision"], saved["title"], saved["owner"], len(saved["shares"])) == (
            3,
            "Again",
            newer,
            1,
        )

    def test_rejects_an_invalid_document(self, store: ArtifactStore) -> None:
        assert store.put(document=document(title=""), owner=OWNER) == err(
            "title: must be a non-empty string"
        )

    def test_reports_an_unwritable_store(self, tmp_path: Path) -> None:
        (tmp_path / "blocker").write_text("")
        store = ArtifactStore(root=tmp_path / "blocker" / "artifacts")

        result = store.put(document=document(), owner=OWNER)

        assert isinstance(result, ErrorResult) and result.error.startswith("Could not write")

    def test_reports_a_corrupt_stored_document(self, store: ArtifactStore) -> None:
        store.root.mkdir(parents=True)
        store.document_path(artifact_id="rollout-review").write_text("{nope")

        result = store.put(document=document(), owner=OWNER)

        assert isinstance(result, ErrorResult) and result.error.startswith("Could not write")


class TestGet:
    @pytest.fixture
    def seeded(self, store: ArtifactStore) -> ArtifactStore:
        store.root.mkdir(parents=True)
        store.document_path(artifact_id="corrupt").write_text("{nope")
        store.document_path(artifact_id="listed").write_text("[]")
        store.document_path(artifact_id="planted\n").write_text(json.dumps(document()))
        return store

    @pytest.mark.parametrize(
        "artifact_id", ["../etc", "planted\n", "missing", "corrupt", "listed"]
    )
    def test_returns_none(self, seeded: ArtifactStore, artifact_id: str) -> None:
        assert seeded.get(artifact_id=artifact_id) is None


class TestIndex:
    def test_newest_first_and_skips_unreadable(self, store: ArtifactStore) -> None:
        store.put(document=document(id="older", title="Older"), owner=OWNER)
        store.put(document=document(id="newer", title="Newer"), owner={})
        store.document_path(artifact_id="broken").write_text("{nope")

        assert store.index() == [
            ArtifactSummary(
                id="newer",
                title="Newer",
                owner={"session_id": "", "name": ""},
                revision=1,
                updated_at=(NOW + timedelta(minutes=1)).isoformat(timespec="seconds"),
            ),
            ArtifactSummary(
                id="older",
                title="Older",
                owner={"session_id": "sid-idle", "name": "mc-updates"},
                revision=1,
                updated_at=NOW.isoformat(timespec="seconds"),
            ),
        ]

    def test_empty_without_a_directory(self, store: ArtifactStore) -> None:
        assert store.index() == []


class TestShares:
    def test_unknown_artifact(self, store: ArtifactStore) -> None:
        assert store.add_share(artifact_id="nope", publisher="p", url="u") == err(
            'No artifact "nope".'
        )

    def test_appends_and_bumps_revision(
        self, store: ArtifactStore, stored: dict[str, Any]
    ) -> None:
        saved = store.add_share(
            artifact_id="rollout-review", publisher="claude-ai", url="https://a"
        ).value  # type: ignore[union-attr]

        assert (saved["revision"], saved["shares"]) == (
            2,
            [
                {
                    "publisher": "claude-ai",
                    "url": "https://a",
                    "at": (NOW + timedelta(minutes=1)).isoformat(timespec="seconds"),
                }
            ],
        )

    def test_reports_an_unwritable_store(
        self, store: ArtifactStore, stored: dict[str, Any]
    ) -> None:
        lock = store.root / "rollout-review.lock"
        lock.unlink(missing_ok=True)
        lock.mkdir()

        result = store.add_share(artifact_id="rollout-review", publisher="p", url="u")

        assert isinstance(result, ErrorResult) and result.error.startswith("Could not write")


class TestEvents:
    def _append(
        self,
        *,
        store: ArtifactStore,
        kind: str = CONTROL_EVENT,
        revision: int = 1,
        control_id: str = "ship",
    ) -> dict[str, Any]:
        return store.append_event(
            event_id=new_event_id(),
            artifact_id="rollout-review",
            kind=kind,
            revision=revision,
            channel="relay",
            detail={"control_id": control_id},
        )

    def test_none_before_the_first(self, store: ArtifactStore) -> None:
        assert store.events(artifact_id="rollout-review") == []

    def test_recent_keeps_the_last(self, store: ArtifactStore) -> None:
        appended = [self._append(store=store, revision=revision) for revision in range(3)]

        assert store.recent_events(artifact_id="rollout-review", limit=2) == appended[1:]

    def test_skips_unreadable_lines(self, store: ArtifactStore) -> None:
        event = self._append(store=store)
        path = store.events_path(artifact_id="rollout-review")
        path.write_text(path.read_text() + "{nope\n[1]\n")

        assert store.events(artifact_id="rollout-review") == [event]

    def test_warns_about_unreadable_lines(
        self, store: ArtifactStore, caplog: pytest.LogCaptureFixture
    ) -> None:
        self._append(store=store)
        path = store.events_path(artifact_id="rollout-review")
        path.write_text(path.read_text() + "{nope\n")

        store.events(artifact_id="rollout-review")

        assert [record.getMessage() for record in caplog.records] == [
            "overwatch artifact rollout-review event log line 2 is unreadable; skipped"
        ]

    def test_event_record(self, store: ArtifactStore) -> None:
        event = self._append(store=store)
        line = json.loads(store.events_path(artifact_id="rollout-review").read_text())

        assert (line, event["at"], event["kind"]) == (
            event,
            NOW.isoformat(timespec="seconds"),
            CONTROL_EVENT,
        )

    @pytest.mark.parametrize(
        ("kind", "revision", "control_id", "sent"),
        [
            (CONTROL_EVENT, 1, "ship", True),
            (CONTROL_EVENT, 2, "ship", False),
            (CONTROL_EVENT, 1, "window", False),
            (SHARE_EVENT, 1, "ship", False),
        ],
    )
    def test_already_sent(
        self,
        store: ArtifactStore,
        kind: str,
        revision: int,
        control_id: str,
        sent: bool,
    ) -> None:
        self._append(store=store, kind=kind, revision=revision, control_id=control_id)

        assert (
            store.already_sent(artifact_id="rollout-review", revision=1, control_id="ship") is sent
        )
