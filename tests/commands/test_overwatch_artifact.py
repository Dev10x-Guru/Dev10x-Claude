"""Tests for `dev10x overwatch artifact` (GH-1938)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner, Result
from dev10x.domain.common.result import err, ok
from tests.comm.overwatch.artifact_fixtures import document

from dev10x.cli import cli
from dev10x.comm.overwatch import paths
from dev10x.comm.overwatch.dev_checkout import DevCheckout
from dev10x.comm.overwatch.owner import ArtifactOwner
from dev10x.commands import overwatch as command

OWNER = ArtifactOwner(session_id="sid-a", name="alpha", cwd="/a")


@pytest.fixture
def owner_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def find_owner(**kwargs: Any) -> object:
        calls.append(kwargs)
        return ok(OWNER)

    monkeypatch.setattr(command, "find_owner", find_owner)
    return calls


@pytest.fixture
def doc_file(tmp_path: Path) -> Path:
    path = tmp_path / "doc.json"
    path.write_text(json.dumps(document()))
    return path


def invoke(*args: str) -> Result:
    return CliRunner().invoke(cli, ["overwatch", "artifact", *args])


@pytest.fixture
def put_once(config_home: Path, owner_calls: list[dict[str, Any]], doc_file: Path) -> Result:
    return invoke("put", str(doc_file), "--session", "alpha")


class TestPut:
    def test_prints_revision_and_url(self, put_once: Result) -> None:
        assert (put_once.exit_code, put_once.output) == (
            0,
            "Artifact rollout-review revision 1: http://127.0.0.1:8765/#/a/rollout-review\n",
        )

    def test_passes_the_session_override(
        self, put_once: Result, owner_calls: list[dict[str, Any]]
    ) -> None:
        assert owner_calls[0]["session"] == "alpha"

    def test_stores_the_owner(self, put_once: Result) -> None:
        stored = json.loads((paths.artifacts_dir() / "rollout-review.json").read_text())

        assert stored["owner"] == OWNER.to_dict()

    def test_dev_instance_uses_its_token_and_port(
        self,
        config_home: Path,
        owner_calls: list[dict[str, Any]],
        doc_file: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        command.write_token(
            token="dev-tok", path=paths.page_token_path(instance=paths.Instance.DEV)
        )
        monkeypatch.setattr(
            command, "load_dev_checkout", lambda: DevCheckout(checkout=Path("/c"), port=9001)
        )

        result = invoke("put", str(doc_file), "--instance", "dev")

        assert result.output == (
            "Artifact rollout-review revision 1: "
            "http://127.0.0.1:9001/?token=dev-tok#/a/rollout-review\n"
        )

    def test_unreadable_json(self, config_home: Path, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("{nope")

        result = invoke("put", str(bad))

        assert (result.exit_code, "is not a readable JSON document" in result.output) == (1, True)

    def test_invalid_document(
        self, config_home: Path, owner_calls: list[dict[str, Any]], tmp_path: Path
    ) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps(document(title="")))

        result = invoke("put", str(bad))

        assert (result.exit_code, result.output) == (
            1,
            "Error: title: must be a non-empty string\n",
        )

    def test_owner_not_found(
        self, config_home: Path, doc_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(command, "find_owner", lambda **kwargs: err("pass --session X"))

        result = invoke("put", str(doc_file))

        assert (result.exit_code, result.output) == (1, "Error: pass --session X\n")


class TestUrl:
    @pytest.mark.parametrize(
        ("args", "url"),
        [
            ([], "http://127.0.0.1:8765/#/a/x\n"),
            (["--instance", "dev"], "http://127.0.0.1:8766/#/a/x\n"),
        ],
        ids=["release", "dev-unpinned"],
    )
    def test_prints_the_page_url(self, config_home: Path, args: list[str], url: str) -> None:
        assert invoke("url", "x", *args).output == url


class TestList:
    def test_empty(self, config_home: Path) -> None:
        assert invoke("list").output == "No artifacts.\n"

    def test_lists_owner(self, put_once: Result) -> None:
        assert invoke("list").output == "rollout-review\tr1\tRollout review\talpha\n"


class TestShared:
    def test_records_the_link(self, put_once: Result) -> None:
        result = invoke(
            "shared", "rollout-review", "--publisher", "claude-ai", "--url", "https://x"
        )
        stored = json.loads((paths.artifacts_dir() / "rollout-review.json").read_text())

        assert (result.output, stored["shares"][0]["url"]) == (
            "Artifact rollout-review revision 2: shared at https://x\n",
            "https://x",
        )

    @pytest.mark.parametrize(
        ("artifact_id", "publisher", "error"),
        [
            (
                "rollout-review",
                "nope",
                'Error: No publisher "nope"; see the page\'s share menu.\n',
            ),
            ("missing", "claude-ai", 'Error: No artifact "missing".\n'),
        ],
    )
    def test_refusals(
        self, put_once: Result, artifact_id: str, publisher: str, error: str
    ) -> None:
        result = invoke("shared", artifact_id, "--publisher", publisher, "--url", "u")

        assert (result.exit_code, result.output) == (1, error)


@pytest.mark.parametrize(
    ("instance", "flag"), [(paths.Instance.RELEASE, ""), (paths.Instance.DEV, " --instance dev")]
)
def test_build_app_wires_artifacts(
    config_home: Path, tmp_path: Path, instance: paths.Instance, flag: str
) -> None:
    app = command.build_app(
        kb_root=tmp_path / "kb",
        bus_root=tmp_path / "bus",
        relay_mailbox="relay",
        token="t",
        instance=instance,
    )

    assert (getattr(app.artifacts, "root", None), app.instance_flag) == (
        paths.artifacts_dir(instance=instance),
        flag,
    )
