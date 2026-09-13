"""The durable config must shrink as well as grow (GH-1253).

Every maintenance command's contract is "ensure X is present", which is
monotone by construction — a measured pass ran ~1,250 additions against
14 removals. Two thirds of `friction.yaml` was pins for ephemeral
worktrees that no longer existed, so first-match-wins evaluation walked
~63 dead entries before reaching a real project, and real defects hid
among them.

The predicate is deliberately narrow, and these tests pin the narrow
half hardest: removing a live entry silently changes a project's
posture, while keeping a dead one costs a glob comparison.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from dev10x.domain.documents.session_yaml import (
    is_provably_dead,
    project_entries,
    reap_dead_projects,
)


def _write(path: Path, projects: list[dict]) -> Path:
    path.write_text(
        yaml.safe_dump({"defaults": {"active_modes": []}, "projects": projects}),
        encoding="utf-8",
    )
    return path


def _entry(*, match: list[str], **prefs) -> dict:
    return {"match": match, **({"supervisor_review": "required"} | prefs)}


def _projects(path: Path) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["projects"]


class TestTheDeadPredicate:
    def test_an_entry_whose_absolute_path_is_gone_is_dead(self, tmp_path: Path) -> None:
        entry = _entry(match=["*/agent-abc", str(tmp_path / "gone")])

        assert is_provably_dead(entry) is True

    def test_an_entry_whose_path_still_exists_is_alive(self, tmp_path: Path) -> None:
        entry = _entry(match=["*/agent-abc", str(tmp_path)])

        assert is_provably_dead(entry) is False

    def test_a_glob_only_entry_is_never_dead(self) -> None:
        # It names no checkout that can be checked. Proving it dead is
        # impossible, so keeping it is the only safe reading.
        entry = _entry(match=["*/tt-pos", "*/tt-pos-*"])

        assert is_provably_dead(entry) is False

    def test_one_surviving_path_keeps_the_entry(self, tmp_path: Path) -> None:
        # "every absolute path absent", not "any" — a repo pinned by both
        # its root and a removed worktree is still live.
        entry = _entry(match=[str(tmp_path / "gone"), str(tmp_path)])

        assert is_provably_dead(entry) is False

    def test_an_entry_without_a_match_list_is_kept(self) -> None:
        assert is_provably_dead({"supervisor_review": "none"}) is False

    @pytest.mark.parametrize("match", [[], ["  "], [None], [123]])
    def test_unusable_match_values_are_kept(self, match: list) -> None:
        assert is_provably_dead({"match": match}) is False


class TestReaping:
    def test_a_dead_entry_is_removed(self, tmp_path: Path) -> None:
        config = _write(
            tmp_path / "friction.yaml",
            [
                _entry(match=["*/agent-dead", str(tmp_path / "gone")]),
                _entry(match=["*/tt-pos"]),
            ],
        )

        report = reap_dead_projects(path=config)

        assert report.reaped == (str(tmp_path / "gone"),)
        assert len(_projects(config)) == 1

    def test_the_surviving_entry_is_unchanged(self, tmp_path: Path) -> None:
        live = _entry(match=["*/tt-pos"], supervisor_review="none")
        config = _write(
            tmp_path / "friction.yaml",
            [_entry(match=[str(tmp_path / "gone")]), live],
        )

        reap_dead_projects(path=config)

        assert _projects(config) == [live]

    def test_order_is_preserved(self, tmp_path: Path) -> None:
        # First-match-wins: reordering survivors would silently change
        # which entry governs a repo.
        config = _write(
            tmp_path / "friction.yaml",
            [
                _entry(match=["*/first"]),
                _entry(match=[str(tmp_path / "gone")]),
                _entry(match=["*/third"]),
            ],
        )

        reap_dead_projects(path=config)

        assert [entry["match"][0] for entry in _projects(config)] == ["*/first", "*/third"]

    def test_nothing_dead_leaves_the_file_alone(self, tmp_path: Path) -> None:
        config = _write(tmp_path / "friction.yaml", [_entry(match=["*/tt-pos"])])
        before = config.read_text(encoding="utf-8")

        report = reap_dead_projects(path=config)

        assert report.changed is False
        assert config.read_text(encoding="utf-8") == before

    def test_defaults_survive_a_reap(self, tmp_path: Path) -> None:
        config = _write(tmp_path / "friction.yaml", [_entry(match=[str(tmp_path / "gone")])])

        reap_dead_projects(path=config)

        doc = yaml.safe_load(config.read_text(encoding="utf-8"))
        assert doc["defaults"] == {"active_modes": []}

    def test_a_missing_file_reports_nothing(self, tmp_path: Path) -> None:
        report = reap_dead_projects(path=tmp_path / "absent.yaml")

        assert report.before == 0
        assert report.changed is False


class TestTheReport:
    def test_counts_before_and_after(self, tmp_path: Path) -> None:
        # The 1250:14 ratio took a separate investigation to obtain; it
        # should be a line of output.
        config = _write(
            tmp_path / "friction.yaml",
            [
                _entry(match=[str(tmp_path / "gone-a")]),
                _entry(match=[str(tmp_path / "gone-b")]),
                _entry(match=["*/live"]),
            ],
        )

        report = reap_dead_projects(path=config)

        assert (report.before, report.after) == (3, 1)

    def test_the_summary_names_what_went(self, tmp_path: Path) -> None:
        config = _write(tmp_path / "friction.yaml", [_entry(match=[str(tmp_path / "gone")])])

        summary = reap_dead_projects(path=config).summary()

        assert "1 → 0" in summary

    def test_a_clean_pass_says_so(self, tmp_path: Path) -> None:
        config = _write(tmp_path / "friction.yaml", [_entry(match=["*/live"])])

        assert "0 provably dead" in reap_dead_projects(path=config).summary()


class TestInspection:
    def test_a_missing_file_has_no_entries(self, tmp_path: Path) -> None:
        # The `--dry-run` read path, and the most likely first invocation:
        # previewing a reap before friction.yaml exists.
        assert project_entries(path=tmp_path / "absent.yaml") == []

    def test_a_file_without_projects_has_no_entries(self, tmp_path: Path) -> None:
        config = tmp_path / "friction.yaml"
        config.write_text(yaml.safe_dump({"defaults": {}}), encoding="utf-8")

        assert project_entries(path=config) == []

    def test_it_returns_the_entries_as_written(self, tmp_path: Path) -> None:
        entry = _entry(match=["*/tt-pos"])
        config = _write(tmp_path / "friction.yaml", [entry])

        assert project_entries(path=config) == [entry]


class TestEntriesWeCannotClassify:
    def test_a_non_dict_entry_is_kept(self, tmp_path: Path) -> None:
        # Nothing here understands it well enough to delete it.
        config = tmp_path / "friction.yaml"
        config.write_text(
            yaml.safe_dump({"projects": ["a bare string", _entry(match=["*/live"])]}),
            encoding="utf-8",
        )

        reap_dead_projects(path=config)

        assert len(_projects(config)) == 2

    def test_the_count_matches_what_the_file_holds(self, tmp_path: Path) -> None:
        # `before` counts the whole list, so `after` cannot disagree with
        # the real survivor count when an unclassifiable entry is present.
        config = tmp_path / "friction.yaml"
        config.write_text(
            yaml.safe_dump(
                {"projects": ["a bare string", _entry(match=[str(tmp_path / "gone")])]}
            ),
            encoding="utf-8",
        )

        report = reap_dead_projects(path=config)

        assert (report.before, report.after) == (2, 1)
        assert len(_projects(config)) == 1
