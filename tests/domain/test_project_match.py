"""Tests for `projects[]` addressing-scheme evaluation (GH-1375, ADR-0026)."""

from __future__ import annotations

import pytest

from dev10x.domain.project_match import (
    MatchScheme,
    ProjectsStatus,
    describe,
    evaluate_projects,
    glob_shape_warnings,
    matches,
    read_patterns,
)


class TestMatchScheme:
    @pytest.mark.parametrize(
        ("scheme", "expected"),
        [(MatchScheme.PATH, "match"), (MatchScheme.REPO, "match_repo")],
    )
    def test_key_names_the_scheme(self, scheme: MatchScheme, expected: str) -> None:
        assert scheme.key == expected


class TestReadPatterns:
    def test_repo_entry_prefers_the_new_key(self) -> None:
        entry = {"match_repo": ["org/*"], "match": ["*/legacy"]}
        assert read_patterns(entry, scheme=MatchScheme.REPO) == (("org/*",), False)

    def test_repo_entry_falls_back_to_the_deprecated_alias(self) -> None:
        entry = {"match": ["org/*"]}
        assert read_patterns(entry, scheme=MatchScheme.REPO) == (("org/*",), True)

    def test_path_entry_never_reports_an_alias(self) -> None:
        entry = {"match": ["/work/dx/**"]}
        assert read_patterns(entry, scheme=MatchScheme.PATH) == (("/work/dx/**",), False)

    def test_path_entry_ignores_the_repo_key(self) -> None:
        entry = {"match_repo": ["org/*"]}
        assert read_patterns(entry, scheme=MatchScheme.PATH) == ((), False)

    def test_scalar_glob_is_accepted(self) -> None:
        assert read_patterns({"match_repo": "org/*"}, scheme=MatchScheme.REPO) == (
            ("org/*",),
            False,
        )

    @pytest.mark.parametrize("entry", ["a stray string", None, 7])
    def test_non_mapping_entry_yields_no_patterns(self, entry: object) -> None:
        assert read_patterns(entry, scheme=MatchScheme.REPO) == ((), False)

    def test_non_string_members_are_dropped(self) -> None:
        assert read_patterns({"match": ["*/a", 3, None]}, scheme=MatchScheme.PATH) == (
            ("*/a",),
            False,
        )

    def test_unsupported_glob_type_yields_no_patterns(self) -> None:
        assert read_patterns({"match": {"a": 1}}, scheme=MatchScheme.PATH) == ((), False)


class TestGlobShapeWarnings:
    def test_org_glob_under_path_key_is_flagged(self) -> None:
        (warning,) = glob_shape_warnings("Dev10x-Guru/*", scheme=MatchScheme.PATH)
        assert "org/repo glob under `match:`" in warning

    @pytest.mark.parametrize("pattern", ["*/dev10x-claude", "/work/dx/**", "dev10x-claude"])
    def test_legitimate_path_globs_are_silent(self, pattern: str) -> None:
        assert glob_shape_warnings(pattern, scheme=MatchScheme.PATH) == ()

    @pytest.mark.parametrize("pattern", ["/work/dx/**", "/abs/path"])
    def test_path_glob_under_repo_key_is_flagged(self, pattern: str) -> None:
        (warning,) = glob_shape_warnings(pattern, scheme=MatchScheme.REPO)
        assert "directory-path glob under `match_repo:`" in warning

    def test_recursive_glob_under_repo_key_is_flagged(self) -> None:
        assert glob_shape_warnings("work/**", scheme=MatchScheme.REPO)

    @pytest.mark.parametrize("pattern", ["org/*", "*/dev10x-claude", "*/tt-pos*"])
    def test_portable_and_org_forms_are_silent_under_repo_key(self, pattern: str) -> None:
        """`*/<repo>` is ADR-0026's documented portable form, never a warning."""
        assert glob_shape_warnings(pattern, scheme=MatchScheme.REPO) == ()


class TestMatches:
    def test_repo_glob_hits_name_with_owner(self) -> None:
        assert matches(
            "Dev10x-Guru/*", target="Dev10x-Guru/Dev10x-Claude", scheme=MatchScheme.REPO
        )

    def test_org_glob_never_hits_a_path(self) -> None:
        assert not matches(
            "Dev10x-Guru/*", target="/work/dx/Dev10x-Claude", scheme=MatchScheme.PATH
        )

    @pytest.mark.parametrize("target", ["/work/dx/Dev10x-Claude", "Dev10x-Guru/Dev10x-Claude"])
    def test_portable_form_resolves_under_both_schemes(self, target: str) -> None:
        scheme = MatchScheme.PATH if target.startswith("/") else MatchScheme.REPO
        assert matches("*/Dev10x-Claude", target=target, scheme=scheme)

    def test_path_glob_matches_the_final_segment(self) -> None:
        assert matches("Dev10x-Claude", target="/work/dx/Dev10x-Claude/", scheme=MatchScheme.PATH)


class TestEvaluateProjects:
    def test_absent_when_no_projects_list(self) -> None:
        report = evaluate_projects(
            {"defaults": {}}, scheme=MatchScheme.REPO, source="f.yaml", target="org/repo"
        )
        assert report.status is ProjectsStatus.ABSENT
        assert report.needs_attention is False

    def test_absent_for_an_empty_list(self) -> None:
        report = evaluate_projects(
            {"projects": []}, scheme=MatchScheme.REPO, source="f.yaml", target="org/repo"
        )
        assert report.status is ProjectsStatus.ABSENT

    def test_absent_for_a_non_mapping_document(self) -> None:
        report = evaluate_projects(
            ["not", "a", "mapping"], scheme=MatchScheme.REPO, source="f.yaml", target="org/repo"
        )
        assert report.status is ProjectsStatus.ABSENT

    def test_matched_names_the_selecting_entry(self) -> None:
        document = {"projects": [{"match_repo": ["other/*"]}, {"match_repo": ["org/*"]}]}
        report = evaluate_projects(
            document, scheme=MatchScheme.REPO, source="f.yaml", target="org/repo"
        )
        assert report.status is ProjectsStatus.MATCHED
        assert report.matched_index == 1
        assert report.needs_attention is False

    def test_only_the_first_match_is_reported(self) -> None:
        document = {"projects": [{"match_repo": ["org/*"]}, {"match_repo": ["org/repo"]}]}
        report = evaluate_projects(
            document, scheme=MatchScheme.REPO, source="f.yaml", target="org/repo"
        )
        assert [entry.matched for entry in report.entries] == [True, False]

    def test_no_match_is_distinct_from_absent(self) -> None:
        document = {"projects": [{"match_repo": ["other/*"]}]}
        report = evaluate_projects(
            document, scheme=MatchScheme.REPO, source="f.yaml", target="org/repo"
        )
        assert report.status is ProjectsStatus.NO_MATCH
        assert report.matched_index is None
        assert report.needs_attention is True

    def test_unresolved_target_is_distinct_from_no_match(self) -> None:
        """ "Did not look" must not read as "looked and found nothing"."""
        document = {"projects": [{"match_repo": ["org/*"]}]}
        report = evaluate_projects(
            document,
            scheme=MatchScheme.REPO,
            source="f.yaml",
            target=None,
            unresolved_reason="no `origin` remote",
        )
        assert report.status is ProjectsStatus.UNRESOLVED
        assert report.entries and report.matched_index is None

    def test_deprecated_alias_is_reported_even_when_it_matches(self) -> None:
        document = {"projects": [{"match": ["org/*"]}]}
        report = evaluate_projects(
            document, scheme=MatchScheme.REPO, source="f.yaml", target="org/repo"
        )
        assert report.status is ProjectsStatus.MATCHED
        assert report.deprecated_alias_indexes == (0,)
        assert report.needs_attention is True

    def test_an_entry_with_no_globs_is_not_an_alias_use(self) -> None:
        document = {"projects": [{"strategy": "rebase"}]}
        report = evaluate_projects(
            document, scheme=MatchScheme.REPO, source="f.yaml", target="org/repo"
        )
        assert report.deprecated_alias_indexes == ()

    def test_shape_warning_survives_an_unresolved_target(self) -> None:
        document = {"projects": [{"match": ["Dev10x-Guru/*"]}]}
        report = evaluate_projects(
            document, scheme=MatchScheme.PATH, source="friction.yaml", target=None
        )
        assert report.shape_warnings and report.shape_warnings[0][0] == 0


class TestDescribe:
    def test_a_healthy_report_says_nothing(self) -> None:
        document = {"projects": [{"match_repo": ["org/*"]}]}
        report = evaluate_projects(
            document, scheme=MatchScheme.REPO, source="f.yaml", target="org/repo"
        )
        assert describe(report) == []

    def test_no_match_names_the_key_and_the_target(self) -> None:
        document = {"projects": [{"match_repo": ["other/*"]}]}
        report = evaluate_projects(
            document, scheme=MatchScheme.REPO, source="f.yaml", target="org/repo"
        )
        rendered = "\n".join(describe(report))
        assert "no `match_repo:` glob matched 'org/repo'" in rendered
        assert "1 entry checked" in rendered

    def test_plural_entry_counts(self) -> None:
        document = {"projects": [{"match_repo": ["a/*"]}, {"match_repo": ["b/*"]}]}
        report = evaluate_projects(
            document, scheme=MatchScheme.REPO, source="f.yaml", target="org/repo"
        )
        assert "2 entries checked" in "\n".join(describe(report))

    def test_unresolved_names_the_reason(self) -> None:
        document = {"projects": [{"match_repo": ["org/*"]}]}
        report = evaluate_projects(
            document,
            scheme=MatchScheme.REPO,
            source="f.yaml",
            target=None,
            unresolved_reason="no `origin` remote",
        )
        rendered = "\n".join(describe(report))
        assert "NOT evaluated" in rendered
        assert "no `origin` remote" in rendered

    def test_unresolved_falls_back_to_a_generic_reason(self) -> None:
        document = {"projects": [{"match_repo": ["a/*"]}, {"match_repo": ["b/*"]}]}
        report = evaluate_projects(document, scheme=MatchScheme.REPO, source="f.yaml", target=None)
        rendered = "\n".join(describe(report))
        assert "2 `projects:` entries NOT evaluated" in rendered
        assert "target could not be determined" in rendered

    def test_alias_and_shape_findings_are_rendered(self) -> None:
        document = {"projects": [{"match": ["/work/dx/**"]}]}
        report = evaluate_projects(
            document, scheme=MatchScheme.REPO, source="f.yaml", target="org/repo"
        )
        rendered = "\n".join(describe(report))
        assert "deprecated alias" in rendered
        assert "directory-path glob under `match_repo:`" in rendered
