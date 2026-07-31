"""Durable preset pinning — repo-stem keying + idempotent merge (GH-855)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from dev10x.domain.common.result import ErrorResult
from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.domain.documents.session_yaml import (
    FrictionYamlDocument,
    match_globs_for_repo,
    repo_stem,
    upsert_project_prefs,
)
from dev10x.session import preset_pin


@pytest.fixture
def friction_path() -> Path:
    """The global friction.yaml, already isolated to a tmp home by conftest."""
    return Dev10xConfigDir.friction_yaml()


@pytest.fixture
def pinned_doc(friction_path: Path) -> Any:
    """Read back the written friction.yaml as a mapping."""

    def read() -> dict[str, Any]:
        return yaml.safe_load(friction_path.read_text()) or {}

    return read


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("bl-zebra-3", "bl-zebra"),
        ("bl-zebra", "bl-zebra"),
        ("Dev10x-Claude-2", "Dev10x-Claude"),
        ("repo-10", "repo"),
        ("repo2", "repo2"),
        ("-3", "-3"),
    ],
)
def test_repo_stem_strips_trailing_worktree_index(name: str, expected: str) -> None:
    assert repo_stem(name) == expected


@pytest.mark.parametrize(
    ("scope", "expected"),
    [
        ("repo", ["*/bl-zebra", "*/bl-zebra-*"]),
        ("repo-only", ["*/bl-zebra"]),
    ],
)
def test_match_globs_for_repo_scopes(scope: str, expected: list[str]) -> None:
    assert match_globs_for_repo(repo_name="bl-zebra", scope=scope) == expected


def test_match_globs_for_repo_dir_scope_uses_literal_path(tmp_path: Path) -> None:
    globs = match_globs_for_repo(repo_name="bl-zebra", repo_root=str(tmp_path), scope="dir")
    assert globs == [os.path.realpath(str(tmp_path))]


def test_match_globs_for_repo_rejects_unknown_scope() -> None:
    with pytest.raises(ValueError, match="unknown pin scope"):
        match_globs_for_repo(repo_name="bl-zebra", scope="galaxy")


def test_match_globs_for_repo_dir_scope_requires_root() -> None:
    with pytest.raises(ValueError, match="requires repo_root"):
        match_globs_for_repo(repo_name="bl-zebra", scope="dir")


@pytest.mark.parametrize("odd_name", ["foo*", "foo?", "foo[ab]", "*"])
def test_match_globs_for_repo_escapes_glob_metacharacters(odd_name: str) -> None:
    """A checkout named `foo*` must not pin a glob matching unrelated repos."""
    globs = match_globs_for_repo(repo_name=odd_name, scope="repo")

    from dev10x.domain.documents.session_yaml import _match_globs

    assert _match_globs(f"/work/{odd_name}", globs) is True
    assert _match_globs("/work/foobar", globs) is False
    assert _match_globs("/work/unrelated-repo", globs) is False


def test_match_globs_for_repo_requires_name() -> None:
    with pytest.raises(ValueError, match="repo_name is required"):
        match_globs_for_repo(repo_name="", scope="repo")


# --- repo-stem glob semantics -----------------------------------------


@pytest.mark.parametrize(
    "checkout",
    ["/work/bl/bl-zebra", "/work/bl/.worktrees/bl-zebra-3", "/work/bl/.worktrees/bl-zebra-9"],
)
def test_repo_scoped_globs_match_main_and_every_worktree(checkout: str) -> None:
    """The AC: main checkout, the pinning worktree, and a future one all match."""
    doc = FrictionYamlDocument.with_project(
        {},
        match=match_globs_for_repo(repo_name="bl-zebra", scope="repo"),
        prefs={"gate_preset": "adaptive"},
    )
    friction = FrictionYamlDocument(toplevel=checkout)
    assert friction  # constructed against the checkout under test
    entry = doc["projects"][0]
    from dev10x.domain.documents.session_yaml import _match_globs

    assert _match_globs(checkout, entry["match"]) is True


def test_repo_scoped_globs_do_not_match_an_unrelated_repo() -> None:
    globs = match_globs_for_repo(repo_name="bl-zebra", scope="repo")
    from dev10x.domain.documents.session_yaml import _match_globs

    assert _match_globs("/work/bl/bl-lion", globs) is False


# --- idempotent merge -------------------------------------------------


def test_with_project_replaces_entry_with_identical_match() -> None:
    doc = FrictionYamlDocument.with_project({}, match=["*/repo"], prefs={"gate_preset": "guided"})
    doc = FrictionYamlDocument.with_project(
        doc, match=["*/repo"], prefs={"gate_preset": "adaptive"}
    )
    assert doc["projects"] == [{"match": ["*/repo"], "gate_preset": "adaptive"}]


def test_with_project_supersedes_a_legacy_worktree_scoped_entry() -> None:
    """A stale `*/bl-zebra-3` key is upgraded in place, not shadowed."""
    doc = {"projects": [{"match": ["*/bl-zebra-3"], "gate_preset": "guided"}]}
    updated = FrictionYamlDocument.with_project(
        doc,
        match=["*/bl-zebra", "*/bl-zebra-*"],
        prefs={"gate_preset": "adaptive"},
        supersedes=["/work/bl/.worktrees/bl-zebra-3"],
    )
    assert updated["projects"] == [
        {"match": ["*/bl-zebra", "*/bl-zebra-*"], "gate_preset": "adaptive"}
    ]


def test_with_project_drops_further_duplicates_for_the_same_repo() -> None:
    doc = {
        "projects": [
            {"match": ["*/bl-zebra-3"], "gate_preset": "guided"},
            {"match": ["*/bl-zebra"], "gate_preset": "strict"},
            {"match": ["*/bl-lion"], "gate_preset": "strict"},
        ]
    }
    updated = FrictionYamlDocument.with_project(
        doc,
        match=["*/bl-zebra", "*/bl-zebra-*"],
        prefs={"gate_preset": "adaptive"},
        supersedes=["/work/bl/bl-zebra", "/work/bl/.worktrees/bl-zebra-3"],
    )
    assert updated["projects"] == [
        {"match": ["*/bl-zebra", "*/bl-zebra-*"], "gate_preset": "adaptive"},
        {"match": ["*/bl-lion"], "gate_preset": "strict"},
    ]


def test_with_project_preserves_unrelated_entries() -> None:
    doc = {"projects": [{"match": ["*/other"], "gate_preset": "strict"}]}
    updated = FrictionYamlDocument.with_project(
        doc, match=["*/repo"], prefs={"gate_preset": "guided"}, supersedes=["/work/repo"]
    )
    assert len(updated["projects"]) == 2
    assert updated["projects"][0]["match"] == ["*/other"]


def test_upsert_project_prefs_honours_an_explicit_match(friction_path: Path) -> None:
    upsert_project_prefs(
        toplevel="/work/bl/.worktrees/bl-zebra-3",
        prefs={"gate_preset": "adaptive"},
        match=["*/bl-zebra", "*/bl-zebra-*"],
    )
    doc = yaml.safe_load(friction_path.read_text())
    assert doc["projects"] == [
        {"match": ["*/bl-zebra", "*/bl-zebra-*"], "gate_preset": "adaptive"}
    ]


# --- repo identity resolution -----------------------------------------


def test_resolve_repo_identity_prefers_the_git_common_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A worktree resolves to the MAIN checkout's name, not its own basename."""
    main = tmp_path / "work" / "bl-zebra"
    (main / ".git").mkdir(parents=True)
    monkeypatch.setattr(preset_pin, "_common_dir", lambda *, cwd: str(main / ".git"))

    identity = preset_pin.resolve_repo_identity(cwd="/work/bl/.worktrees/bl-zebra-3").value

    assert identity["name"] == "bl-zebra"
    assert identity["root"] == os.path.realpath(str(main))
    assert identity["source"] == "git-common-dir"


def test_resolve_repo_identity_does_not_stem_the_common_dir_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`advent-2024` is a real repo name — stemming it would over-widen."""
    main = tmp_path / "advent-2024"
    (main / ".git").mkdir(parents=True)
    monkeypatch.setattr(preset_pin, "_common_dir", lambda *, cwd: str(main / ".git"))

    assert preset_pin.resolve_repo_identity().value["name"] == "advent-2024"


def test_resolve_repo_identity_handles_a_bare_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preset_pin, "_common_dir", lambda *, cwd: "/srv/git/bl-zebra.git")

    identity = preset_pin.resolve_repo_identity().value

    assert identity["name"] == "bl-zebra"
    assert identity["root"] is None
    assert identity["source"] == "bare-repo"


def test_resolve_repo_identity_handles_a_custom_git_dir_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A `GIT_DIR` that is neither `.git` nor `*.git` names the repo itself."""
    custom = tmp_path / "bl-zebra-metadata"
    custom.mkdir()
    monkeypatch.setattr(preset_pin, "_common_dir", lambda *, cwd: str(custom))

    identity = preset_pin.resolve_repo_identity().value

    assert identity["name"] == "bl-zebra-metadata"
    assert identity["root"] == os.path.realpath(str(custom))


def test_resolve_repo_identity_falls_back_to_a_stemmed_basename(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(preset_pin, "_common_dir", lambda *, cwd: None)
    monkeypatch.setattr(
        preset_pin, "_bounded_toplevel", lambda *, cwd: "/work/bl/.worktrees/bl-zebra-3"
    )

    identity = preset_pin.resolve_repo_identity().value

    assert identity["name"] == "bl-zebra"
    assert identity["source"] == "worktree-basename"


def test_resolve_repo_identity_errors_outside_a_git_repo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(preset_pin, "_common_dir", lambda *, cwd: None)
    monkeypatch.setattr(preset_pin, "_bounded_toplevel", lambda *, cwd: None)

    result = preset_pin.resolve_repo_identity()

    assert isinstance(result, ErrorResult)
    assert "Not in a git repository" in result.error


@pytest.mark.parametrize(
    "failure",
    [
        OSError("no git here"),
        subprocess.CalledProcessError(128, "git"),
        subprocess.TimeoutExpired("git", 10.0),
    ],
)
def test_common_dir_returns_none_when_git_fails(
    monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    """Every failure mode degrades to the basename fallback, never raises."""

    def boom(self: object, *args: str, **kwargs: object) -> str:
        raise failure

    monkeypatch.setattr("dev10x.domain.git_context.GitContext.run", boom)

    assert preset_pin._common_dir(cwd=None) is None


@pytest.mark.parametrize(
    ("helper", "stdout"),
    [("_common_dir", "/work/bl/bl-zebra/.git"), ("_bounded_toplevel", "/work/bl/bl-zebra")],
)
def test_git_lookups_are_bounded(
    monkeypatch: pytest.MonkeyPatch, helper: str, stdout: str
) -> None:
    """The MCP daemon serves these on the Phase-0 hot path — they must not hang."""
    seen: dict[str, object] = {}

    def record(self: object, *args: str, **kwargs: object) -> str:
        seen.update(kwargs)
        return stdout

    monkeypatch.setattr("dev10x.domain.git_context.GitContext.run", record)

    getattr(preset_pin, helper)(cwd=None)

    assert seen["timeout"] == preset_pin._GIT_TIMEOUT_SECONDS


@pytest.mark.parametrize(
    "failure",
    [
        OSError("no git here"),
        subprocess.CalledProcessError(128, "git"),
        subprocess.TimeoutExpired("git", 10.0),
    ],
)
def test_bounded_toplevel_returns_none_when_git_fails(
    monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    def boom(self: object, *args: str, **kwargs: object) -> str:
        raise failure

    monkeypatch.setattr("dev10x.domain.git_context.GitContext.run", boom)

    assert preset_pin._bounded_toplevel(cwd=None) is None


def test_bounded_toplevel_treats_empty_output_as_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("dev10x.domain.git_context.GitContext.run", lambda self, *a, **k: "")

    assert preset_pin._bounded_toplevel(cwd=None) is None


# --- pin + status end to end ------------------------------------------


@pytest.fixture
def zebra_repo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Pretend every call comes from a worktree of the `bl-zebra` repo."""
    main = tmp_path / "work" / "bl-zebra"
    (main / ".git").mkdir(parents=True)
    monkeypatch.setattr(preset_pin, "_common_dir", lambda *, cwd: str(main / ".git"))
    return main


def test_pin_preset_writes_a_repo_stem_entry(
    zebra_repo: Path, friction_path: Path, pinned_doc: Any
) -> None:
    """AC: picking in worktree `<repo>-3` saves the repo-stem glob."""
    result = preset_pin.pin_preset(preset="adaptive", cwd="/work/bl/.worktrees/bl-zebra-3")

    assert result.value["match"] == ["*/bl-zebra", "*/bl-zebra-*"]
    assert pinned_doc()["projects"] == [
        {"match": ["*/bl-zebra", "*/bl-zebra-*"], "gate_preset": "adaptive"}
    ]


def test_pin_preset_records_overlays_and_overrides(
    zebra_repo: Path, friction_path: Path, pinned_doc: Any
) -> None:
    preset_pin.pin_preset(
        preset="guided",
        overlays=["solo-maintainer"],
        gate_overrides={"merge": "ask"},
    )

    entry = pinned_doc()["projects"][0]
    assert entry["gate_overlays"] == ["solo-maintainer"]
    assert entry["gate_overrides"] == {"merge": "ask"}


def test_pin_preset_is_idempotent_across_worktrees(
    zebra_repo: Path, friction_path: Path, pinned_doc: Any
) -> None:
    """AC: never duplicate — a second pick from a sibling worktree updates."""
    preset_pin.pin_preset(preset="guided", cwd="/work/bl/.worktrees/bl-zebra-1")
    preset_pin.pin_preset(preset="adaptive", cwd="/work/bl/.worktrees/bl-zebra-7")

    projects = pinned_doc()["projects"]
    assert len(projects) == 1
    assert projects[0]["gate_preset"] == "adaptive"


def test_pin_preset_absorbs_a_legacy_worktree_scoped_entry(
    zebra_repo: Path,
    friction_path: Path,
    pinned_doc: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pre-GH-855 `*/bl-zebra-3` key is upgraded, not left shadowing."""
    friction_path.parent.mkdir(parents=True, exist_ok=True)
    friction_path.write_text(
        yaml.safe_dump({"projects": [{"match": ["*/bl-zebra-3"], "gate_preset": "guided"}]})
    )
    monkeypatch.setattr(
        preset_pin, "_bounded_toplevel", lambda *, cwd: "/work/bl/.worktrees/bl-zebra-3"
    )

    preset_pin.pin_preset(preset="adaptive", cwd="/work/bl/.worktrees/bl-zebra-3")

    assert pinned_doc()["projects"] == [
        {"match": ["*/bl-zebra", "*/bl-zebra-*"], "gate_preset": "adaptive"}
    ]


def test_pin_preset_repo_only_scope_omits_the_worktree_glob(
    zebra_repo: Path, friction_path: Path
) -> None:
    result = preset_pin.pin_preset(preset="strict", scope="repo-only")

    assert result.value["match"] == ["*/bl-zebra"]


def test_pin_preset_dir_scope_uses_the_literal_repo_root(
    zebra_repo: Path, friction_path: Path
) -> None:
    result = preset_pin.pin_preset(preset="strict", scope="dir")

    assert result.value["match"] == [os.path.realpath(str(zebra_repo))]


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"preset": "adaptiv"}, "unknown preset"),
        ({"preset": "guided", "overlays": ["sollo-maintainer"]}, "unknown overlay"),
        ({"preset": "guided", "gate_overrides": {"marge": "ask"}}, "unknown gate"),
        ({"preset": "guided", "gate_overrides": {"merge": "atuo-advance"}}, "invalid value"),
    ],
)
def test_pin_preset_rejects_values_that_would_poison_resolve_gate(
    zebra_repo: Path,
    friction_path: Path,
    kwargs: dict[str, Any],
    expected: str,
) -> None:
    """An invalid pin would make every later resolve_gate for this repo error."""
    result = preset_pin.pin_preset(**kwargs)

    assert isinstance(result, ErrorResult)
    assert expected in result.error
    assert not friction_path.exists()


def test_pin_preset_accepts_a_user_defined_preset(
    zebra_repo: Path, friction_path: Path, monkeypatch: pytest.MonkeyPatch, pinned_doc: Any
) -> None:
    """Validation must not be stricter than the resolver (user presets are legal)."""
    monkeypatch.setattr(
        "dev10x.config.friction_presets.load_user_presets", lambda **_: {"house-style": {}}
    )

    result = preset_pin.pin_preset(preset="house-style")

    assert not isinstance(result, ErrorResult)
    assert pinned_doc()["projects"][0]["gate_preset"] == "house-style"


def test_pin_preset_rejects_an_unknown_scope(zebra_repo: Path, friction_path: Path) -> None:
    result = preset_pin.pin_preset(preset="strict", scope="galaxy")

    assert isinstance(result, ErrorResult)
    assert "unknown pin scope" in result.error


def test_pin_preset_dir_scope_errors_on_a_bare_repo(
    monkeypatch: pytest.MonkeyPatch, friction_path: Path
) -> None:
    monkeypatch.setattr(preset_pin, "_common_dir", lambda *, cwd: "/srv/git/bl-zebra.git")

    result = preset_pin.pin_preset(preset="strict", scope="dir")

    assert isinstance(result, ErrorResult)
    assert "bare" in result.error


def test_pin_preset_re_pins_a_bare_repo_without_duplicating(
    monkeypatch: pytest.MonkeyPatch, friction_path: Path, pinned_doc: Any
) -> None:
    """A bare repo has no working tree — the never-duplicate invariant still holds."""
    monkeypatch.setattr(preset_pin, "_common_dir", lambda *, cwd: "/srv/git/bl-zebra.git")
    monkeypatch.setattr(preset_pin, "_bounded_toplevel", lambda *, cwd: None)

    preset_pin.pin_preset(preset="guided")
    preset_pin.pin_preset(preset="adaptive")

    assert pinned_doc()["projects"] == [
        {"match": ["*/bl-zebra", "*/bl-zebra-*"], "gate_preset": "adaptive"}
    ]


def test_preset_pin_status_sees_a_bare_repo_pin(
    monkeypatch: pytest.MonkeyPatch, friction_path: Path
) -> None:
    monkeypatch.setattr(preset_pin, "_common_dir", lambda *, cwd: "/srv/git/bl-zebra.git")
    monkeypatch.setattr(preset_pin, "_bounded_toplevel", lambda *, cwd: None)

    preset_pin.pin_preset(preset="adaptive")

    assert preset_pin.preset_pin_status().value["pinned"] is True


def test_pin_preset_propagates_an_identity_error(
    monkeypatch: pytest.MonkeyPatch, friction_path: Path
) -> None:
    monkeypatch.setattr(preset_pin, "_common_dir", lambda *, cwd: None)
    monkeypatch.setattr(preset_pin, "_bounded_toplevel", lambda *, cwd: None)

    result = preset_pin.pin_preset(preset="strict")

    assert isinstance(result, ErrorResult)


def test_preset_pin_status_is_unpinned_before_the_first_pick(
    zebra_repo: Path, friction_path: Path
) -> None:
    """AC: the gate fires only on the first pick."""
    status = preset_pin.preset_pin_status(cwd="/work/bl/.worktrees/bl-zebra-3").value

    assert status["pinned"] is False
    assert status["repo_name"] == "bl-zebra"
    assert status["suggested_match"] == ["*/bl-zebra", "*/bl-zebra-*"]


def test_preset_pin_status_is_pinned_after_a_pick(zebra_repo: Path, friction_path: Path) -> None:
    """AC: the next session in ANY worktree matches — no re-ask."""
    preset_pin.pin_preset(preset="adaptive", cwd="/work/bl/.worktrees/bl-zebra-3")

    status = preset_pin.preset_pin_status(cwd="/work/bl/.worktrees/bl-zebra-9").value

    assert status["pinned"] is True
    assert status["prefs"]["gate_preset"] == "adaptive"


def test_preset_pin_status_reports_a_bare_repo(
    monkeypatch: pytest.MonkeyPatch, friction_path: Path
) -> None:
    monkeypatch.setattr(preset_pin, "_common_dir", lambda *, cwd: "/srv/git/bl-zebra.git")

    status = preset_pin.preset_pin_status().value

    assert status["repo_root"] is None
    assert status["pinned"] is False


def test_preset_pin_status_propagates_an_identity_error(
    monkeypatch: pytest.MonkeyPatch, friction_path: Path
) -> None:
    monkeypatch.setattr(preset_pin, "_common_dir", lambda *, cwd: None)
    monkeypatch.setattr(preset_pin, "_bounded_toplevel", lambda *, cwd: None)

    assert isinstance(preset_pin.preset_pin_status(), ErrorResult)


# --- ADR-0018 invariant -----------------------------------------------


def test_pin_preset_writes_nothing_under_any_repo_dot_claude(
    zebra_repo: Path, friction_path: Path, tmp_path: Path
) -> None:
    """ADR-0018: the self-settings gate must never fire on a pin."""
    preset_pin.pin_preset(preset="adaptive", cwd=str(zebra_repo))

    assert friction_path.exists()
    assert list(tmp_path.rglob(".claude")) == []
