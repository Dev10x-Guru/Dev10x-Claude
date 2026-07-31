from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev10x.domain.common.result import ErrorResult, SuccessResult
from dev10x.domain.plugin_origin import (
    load_marketplace_sources,
    repo_from_url,
    resolve_plugin_origin,
    resolve_skill_origins,
)

_MARKETPLACES = {
    "Dev10x-Guru": {"source": {"source": "github", "repo": "Dev10x-Guru/dev10x-claude"}},
    "impeccable": {"source": {"source": "github", "repo": "pbakaus/impeccable"}},
    "obsidian-cli-skill": {
        "source": {
            "source": "git",
            "url": "https://github.com/pablo-mano/Obsidian-CLI-skill.git",
        }
    },
    "TireTutor": {
        "source": {"source": "git", "url": "git@github.com:tiretutorinc/tt-witcher.git"}
    },
    "no-source": {"installLocation": "/somewhere"},
    "blank-source": {"source": {"source": "local"}},
}


@pytest.fixture
def plugins_root(tmp_path: Path) -> Path:
    root = tmp_path / "plugins"
    root.mkdir()
    (root / "known_marketplaces.json").write_text(json.dumps(_MARKETPLACES), encoding="utf-8")
    return root


@pytest.fixture
def dev10x_skill(plugins_root: Path) -> str:
    return str(plugins_root / "cache/Dev10x-Guru/Dev10x/0.91.0/skills/skill-audit/SKILL.md")


@pytest.fixture
def foreign_skill(plugins_root: Path) -> str:
    return str(plugins_root / "cache/impeccable/impeccable/1.3.0/skills/polish/SKILL.md")


@pytest.mark.parametrize(
    "url,expected",
    [
        ("git@github.com:tiretutorinc/tt-witcher.git", "tiretutorinc/tt-witcher"),
        ("https://github.com/pablo-mano/Obsidian-CLI-skill.git", "pablo-mano/Obsidian-CLI-skill"),
        ("https://github.com/owner/name", "owner/name"),
        ("ssh://git@github.com/owner/name.git", "owner/name"),
        ("not-a-url", None),
        ("", None),
    ],
)
def test_repo_from_url(url: str, expected: str | None) -> None:
    assert repo_from_url(url=url) == expected


def test_resolves_dev10x_cache_layout(plugins_root: Path, dev10x_skill: str) -> None:
    result = resolve_plugin_origin(skill_path=dev10x_skill, plugins_root=plugins_root)

    assert isinstance(result, SuccessResult)
    origin = result.value
    assert origin.marketplace == "Dev10x-Guru"
    assert origin.plugin == "Dev10x"
    assert origin.version == "0.91.0"
    assert origin.repo == "Dev10x-Guru/dev10x-claude"
    assert origin.issue_tracker == "https://github.com/Dev10x-Guru/dev10x-claude/issues"
    assert origin.is_dev10x is True


def test_resolves_foreign_plugin_to_its_own_tracker(
    plugins_root: Path,
    foreign_skill: str,
) -> None:
    result = resolve_plugin_origin(skill_path=foreign_skill, plugins_root=plugins_root)

    assert isinstance(result, SuccessResult)
    assert result.value.repo == "pbakaus/impeccable"
    assert result.value.is_dev10x is False


def test_resolves_git_url_marketplace(plugins_root: Path) -> None:
    skill = plugins_root / "cache/TireTutor/witcher/0.6.0.dev0/skills/tt-db/SKILL.md"

    result = resolve_plugin_origin(skill_path=str(skill), plugins_root=plugins_root)

    assert isinstance(result, SuccessResult)
    assert result.value.repo == "tiretutorinc/tt-witcher"
    assert result.value.source_kind == "git"


def test_resolves_marketplaces_layout_without_version(plugins_root: Path) -> None:
    skill = plugins_root / "marketplaces/impeccable/impeccable/skills/polish/SKILL.md"

    result = resolve_plugin_origin(skill_path=str(skill), plugins_root=plugins_root)

    assert isinstance(result, SuccessResult)
    assert result.value.version is None
    assert result.value.repo == "pbakaus/impeccable"


@pytest.mark.parametrize("marketplace", ["no-source", "blank-source", "never-installed"])
def test_missing_marketplace_entry_resolves_without_tracker(
    plugins_root: Path,
    marketplace: str,
) -> None:
    skill = plugins_root / f"cache/{marketplace}/someplugin/1.0.0/skills/x/SKILL.md"

    result = resolve_plugin_origin(skill_path=str(skill), plugins_root=plugins_root)

    assert isinstance(result, SuccessResult)
    assert result.value.plugin == "someplugin"
    assert result.value.repo is None
    assert result.value.issue_tracker is None
    assert result.value.is_dev10x is False


@pytest.mark.parametrize(
    "relative",
    ["cache/only-marketplace", "cache", "repos/foo/bar/skills/x", "known_marketplaces.json"],
)
def test_malformed_path_under_root_is_an_error(plugins_root: Path, relative: str) -> None:
    result = resolve_plugin_origin(
        skill_path=str(plugins_root / relative),
        plugins_root=plugins_root,
    )

    assert isinstance(result, ErrorResult)
    assert "does not name a plugin" in result.error


def test_path_outside_plugins_root_is_an_error(plugins_root: Path, tmp_path: Path) -> None:
    result = resolve_plugin_origin(
        skill_path=str(tmp_path / "skills/local-skill/SKILL.md"),
        plugins_root=plugins_root,
    )

    assert isinstance(result, ErrorResult)
    assert "not under the plugins root" in result.error


def test_relative_path_is_an_error(plugins_root: Path) -> None:
    result = resolve_plugin_origin(skill_path="cache/x/y/1.0/skills/z", plugins_root=plugins_root)

    assert isinstance(result, ErrorResult)
    assert "not absolute" in result.error


def test_missing_marketplaces_catalog_yields_empty_sources(tmp_path: Path) -> None:
    assert load_marketplace_sources(marketplaces_path=tmp_path / "absent.json") == {}


def test_malformed_marketplaces_catalog_yields_empty_sources(tmp_path: Path) -> None:
    path = tmp_path / "known_marketplaces.json"
    path.write_text("{not json", encoding="utf-8")

    assert load_marketplace_sources(marketplaces_path=path) == {}


def test_non_object_marketplaces_catalog_yields_empty_sources(tmp_path: Path) -> None:
    path = tmp_path / "known_marketplaces.json"
    path.write_text('["a", "b"]', encoding="utf-8")

    assert load_marketplace_sources(marketplaces_path=path) == {}


def test_skill_origins_group_findings_across_plugins(
    plugins_root: Path,
    dev10x_skill: str,
    foreign_skill: str,
) -> None:
    result = resolve_skill_origins(
        skill_paths=[dev10x_skill, foreign_skill, dev10x_skill],
        plugins_root=plugins_root,
    )

    assert isinstance(result, SuccessResult)
    payload = result.value
    assert payload["target_count"] == 2
    assert payload["unresolved_count"] == 0
    by_repo = {target["repo"]: target for target in payload["targets"]}
    assert len(by_repo["Dev10x-Guru/dev10x-claude"]["skill_paths"]) == 2
    assert by_repo["pbakaus/impeccable"]["issue_tracker"] == (
        "https://github.com/pbakaus/impeccable/issues"
    )


def test_skill_origins_report_untrackable_paths_as_unresolved(
    plugins_root: Path,
    tmp_path: Path,
) -> None:
    outside = str(tmp_path / "skills/local/SKILL.md")
    trackerless = str(plugins_root / "cache/no-source/plug/1.0.0/skills/x/SKILL.md")

    result = resolve_skill_origins(skill_paths=[outside, trackerless], plugins_root=plugins_root)

    assert isinstance(result, SuccessResult)
    payload = result.value
    assert payload["target_count"] == 0
    assert payload["unresolved_count"] == 2
    reasons = [entry["reason"] for entry in payload["unresolved"]]
    assert any("not under the plugins root" in reason for reason in reasons)
    assert any("no resolvable source repo" in reason for reason in reasons)


def test_skill_origins_rejects_empty_input(plugins_root: Path) -> None:
    result = resolve_skill_origins(skill_paths=[], plugins_root=plugins_root)

    assert isinstance(result, ErrorResult)
    assert result.error == "no skill paths provided"
