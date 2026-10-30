"""Triage-then-grant everywhere (GH-1676)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from dev10x.domain.common.result import ErrorResult, SuccessResult
from dev10x.domain.rules.validation_rule import Compensation, MatchingRule
from dev10x.skills.permission.grant import Verdict

from dev10x.skills.permission import catalog_write
from dev10x.skills.permission import grant as mod


@pytest.fixture(autouse=True)
def _untracked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(catalog_write, "_is_git_tracked", lambda _path: False)


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    return path


@pytest.fixture
def skill_map() -> list[MatchingRule]:
    return [
        MatchingRule(
            name="gh-pr-view",
            patterns=[r"^gh pr view"],
            compensations=[Compensation(type="use-tool", tool="mcp__plugin_dev10x_cli__pr_get")],
        )
    ]


def _settings(
    path: Path, *, allow: list[str] | None = None, deny: list[str] | None = None
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"permissions": {"allow": allow or [], "deny": deny or []}}))
    return path


@pytest.fixture
def global_settings(tmp_path: Path) -> Path:
    return _settings(tmp_path / "home" / ".claude" / "settings.json")


@pytest.fixture
def project_settings(workdir: Path) -> Path:
    return _settings(workdir / ".claude" / "settings.local.json")


@pytest.fixture
def settings_files(global_settings: Path, project_settings: Path) -> list[Path]:
    return [global_settings, project_settings]


def _allow(path: Path) -> list[str]:
    return json.loads(path.read_text())["permissions"]["allow"]


def _triage(
    *,
    target: str,
    settings_files: list[Path],
    workdir: Path,
    skill_map: list[MatchingRule],
    base_denies: list[str] | None = None,
) -> mod.Triage:
    return mod.triage(
        target=target,
        settings_files=settings_files,
        working_dirs=[workdir],
        base_denies=base_denies or [],
        skill_map_rules=skill_map,
    )


class TestDeriveRule:
    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("rg -n foo src/", "Bash(rg:*)"),
            ("git status --short", "Bash(git status:*)"),
            ("gh pr list --limit 5", "Bash(gh pr list:*)"),
            ("docker build .", "Bash(docker build:*)"),
            ("", ""),
        ],
    )
    def test_keeps_tool_subcommands(self, command: str, expected: str) -> None:
        assert mod.derive_rule(command=command) == expected

    @pytest.mark.parametrize(
        "command",
        ["git -C /x status", "git -c x=y log", "docker --version", "gh pr", "gh"],
    )
    def test_unreadable_subcommand_derives_no_rule(self, command: str) -> None:
        assert mod.derive_rule(command=command) == ""


class TestBreadthProblem:
    @pytest.mark.parametrize(
        "rule",
        [
            "",
            "Bash(*)",
            "Bash(:*)",
            "Bash(sudo:*)",
            "Bash(/usr/bin/bash:*)",
            "Bash(git:*)",
            "Bash(gh pr:*)",
            "Bash(gh api:*)",
            "Bash(git push:*)",
            "Bash(uv run:*)",
            "Bash(git * status:*)",
            "Read(//**)",
            "Read(~/**)",
            "Edit(**/*.py)",
            "mcp__*",
            "mcp__plugin_dev10x_cli__*",
        ],
    )
    def test_flags_broad_rules(self, rule: str) -> None:
        assert mod.breadth_problem(rule=rule) is not None

    @pytest.mark.parametrize(
        "rule",
        [
            "Bash(rg:*)",
            "Bash(make:*)",
            "Bash(git status:*)",
            "Bash(gh pr view:*)",
            "Read(~/.claude/plugins/**)",
            "Skill(dev10x:git)",
            "mcp__plugin_dev10x_cli__pr_get",
        ],
    )
    def test_accepts_narrow_rules(self, rule: str) -> None:
        assert mod.breadth_problem(rule=rule) is None

    @pytest.mark.parametrize(
        ("rule", "expected"),
        [
            ("Bash(git status:*)", "git status"),
            ("Bash(make test *)", "make test"),
            ("Read(~/x)", None),
        ],
    )
    def test_bash_prefix(self, rule: str, expected: str | None) -> None:
        assert mod.bash_prefix(rule=rule) == expected


class TestAlternativeAdvice:
    @pytest.mark.parametrize(
        ("compensation", "expected"),
        [
            (Compensation(type="use-skill", skill="dev10x:git"), "Skill(dev10x:git)"),
            (Compensation(type="use-tool", tool="Glob"), "Glob"),
            (Compensation(type="use-alternative", alias="git develop-log"), "git develop-log"),
            (Compensation(type="use-alternative", description="Use Read"), "Use Read"),
            (Compensation(type="use-alternative"), "use-alternative"),
        ],
    )
    def test_names_the_route(
        self,
        compensation: Compensation,
        expected: str,
        settings_files: list[Path],
        workdir: Path,
    ) -> None:
        routed = [MatchingRule(name="r", patterns=[r"^make"], compensations=[compensation])]
        result = _triage(
            target="make test",
            settings_files=settings_files,
            workdir=workdir,
            skill_map=routed,
        )
        assert result.advice == [expected]


class TestIsRule:
    @pytest.mark.parametrize(
        ("target", "expected"),
        [
            ("mcp__plugin_dev10x_cli__pr_get", True),
            ("Read(~/.claude/**)", True),
            ("Bash(rg:*)", True),
            ("rg -n foo", False),
        ],
    )
    def test_detects_rule_shape(self, target: str, expected: bool) -> None:
        assert mod.is_rule(target) is expected


class TestTriageVerdicts:
    @pytest.mark.parametrize(
        ("target", "expected"),
        [
            ("cat ~/.aws/credentials", Verdict.REFUSE_SENSITIVE),
            ("gh secret list", Verdict.REFUSE_SENSITIVE),
            ("mcp__claude_ai_Slack__read_private_dm_messages", Verdict.REFUSE_SENSITIVE),
            ("gh pr view 12", Verdict.USE_ALTERNATIVE),
            ("git status && git log", Verdict.NORMALIZE),
            ("ls ${HOME}", Verdict.NORMALIZE),
            ('rg "a\\"b" src', Verdict.NORMALIZE),
            ("FOO=1 make test", Verdict.NORMALIZE),
            ("echo hi > out.txt", Verdict.NORMALIZE),
            ("rg pattern /etc/hosts", Verdict.OUTSIDE_WORKDIR),
            ("rg x ~/.ssh", Verdict.REFUSE_SENSITIVE),
            ("ls ~/.aws", Verdict.REFUSE_SENSITIVE),
            ("Read(~/.aws/**)", Verdict.REFUSE_SENSITIVE),
            ("Read(**/.env*)", Verdict.REFUSE_SENSITIVE),
            ("Read(~/.config/gh/**)", Verdict.REFUSE_SENSITIVE),
            ("Read(~/.config/gh-dash/**)", Verdict.GRANT),
            ("cat $HOME/notes", Verdict.NORMALIZE),
            ("cat ../../../../../../etc/shadow-copy", Verdict.OUTSIDE_WORKDIR),
            ("", Verdict.TOO_BROAD),
            ("   ", Verdict.TOO_BROAD),
            ('bash -c "ls"', Verdict.TOO_BROAD),
            ("sudo ls", Verdict.TOO_BROAD),
            ("env X=1 make", Verdict.TOO_BROAD),
            ("git -C /x status", Verdict.TOO_BROAD),
            ("Bash(*)", Verdict.TOO_BROAD),
            ("Bash(sudo:*)", Verdict.TOO_BROAD),
            ("Read(//**)", Verdict.TOO_BROAD),
            ("Bash(cat /etc/hosts:*)", Verdict.OUTSIDE_WORKDIR),
            ("Bash(git status && git log:*)", Verdict.NORMALIZE),
            ("Bash(gh pr view:*)", Verdict.USE_ALTERNATIVE),
            ("make test", Verdict.GRANT),
            ("mcp__plugin_dev10x_cli__pr_get", Verdict.GRANT),
        ],
    )
    def test_first_matching_fix_wins(
        self,
        target: str,
        expected: Verdict,
        settings_files: list[Path],
        workdir: Path,
        skill_map: list[MatchingRule],
    ) -> None:
        result = _triage(
            target=target,
            settings_files=settings_files,
            workdir=workdir,
            skill_map=skill_map,
        )
        assert result.verdict is expected

    def test_deny_in_any_file_blocks_grant(
        self,
        tmp_path: Path,
        project_settings: Path,
        workdir: Path,
        skill_map: list[MatchingRule],
    ) -> None:
        denying = _settings(tmp_path / "other" / "settings.local.json", deny=["Bash(make test:*)"])
        result = _triage(
            target="make test",
            settings_files=[project_settings, denying],
            workdir=workdir,
            skill_map=skill_map,
        )
        assert result.verdict is Verdict.DENIED

    def test_catalog_deny_blocks_grant(
        self,
        settings_files: list[Path],
        workdir: Path,
        skill_map: list[MatchingRule],
    ) -> None:
        result = _triage(
            target="make test",
            settings_files=settings_files,
            workdir=workdir,
            skill_map=skill_map,
            base_denies=["Bash(make test:*)"],
        )
        assert result.verdict is Verdict.DENIED

    @pytest.mark.parametrize(
        ("deny", "expected"),
        [
            ("Bash(make deploy:*)", Verdict.DENIED),
            ("Bash(makefile-lint:*)", Verdict.GRANT),
            ("Read(~/x)", Verdict.GRANT),
        ],
    )
    def test_rule_wider_than_a_deny_is_refused(
        self,
        deny: str,
        expected: Verdict,
        settings_files: list[Path],
        workdir: Path,
        skill_map: list[MatchingRule],
    ) -> None:
        result = _triage(
            target="make build",
            settings_files=settings_files,
            workdir=workdir,
            skill_map=skill_map,
            base_denies=[deny],
        )
        assert result.verdict is expected

    def test_route_without_compensation_does_not_shadow_a_later_route(
        self,
        settings_files: list[Path],
        workdir: Path,
    ) -> None:
        rules = [
            MatchingRule(name="advisory", patterns=[r"^make"]),
            MatchingRule(
                name="routed",
                patterns=[r"^make"],
                compensations=[Compensation(type="use-skill", skill="dev10x:x")],
            ),
        ]
        result = _triage(
            target="make build",
            settings_files=settings_files,
            workdir=workdir,
            skill_map=rules,
        )
        assert (result.verdict, result.advice) == (Verdict.USE_ALTERNATIVE, ["Skill(dev10x:x)"])

    def test_read_inside_workdir_is_grantable(
        self,
        settings_files: list[Path],
        workdir: Path,
        skill_map: list[MatchingRule],
    ) -> None:
        result = _triage(
            target=f"rg pattern {workdir}/src",
            settings_files=settings_files,
            workdir=workdir,
            skill_map=skill_map,
        )
        assert result.verdict is Verdict.GRANT

    @pytest.mark.parametrize("operand", ["{workdir}/../outside", "../outside"])
    def test_dot_dot_escape_is_outside(
        self,
        operand: str,
        settings_files: list[Path],
        workdir: Path,
        skill_map: list[MatchingRule],
    ) -> None:
        result = _triage(
            target=f"rg pattern {operand.format(workdir=workdir)}",
            settings_files=settings_files,
            workdir=workdir,
            skill_map=skill_map,
        )
        assert result.verdict is Verdict.OUTSIDE_WORKDIR

    def test_relative_operand_inside_workdir_is_grantable(
        self,
        settings_files: list[Path],
        workdir: Path,
        skill_map: list[MatchingRule],
    ) -> None:
        result = _triage(
            target="rg pattern src/app",
            settings_files=settings_files,
            workdir=workdir,
            skill_map=skill_map,
        )
        assert result.verdict is Verdict.GRANT

    def test_outside_workdir_recommends_directory_and_read_rule(
        self,
        settings_files: list[Path],
        workdir: Path,
        skill_map: list[MatchingRule],
    ) -> None:
        result = _triage(
            target="rg pattern /etc/hosts",
            settings_files=settings_files,
            workdir=workdir,
            skill_map=skill_map,
        )
        assert result.advice == [
            "Add /etc to permissions.additionalDirectories",
            "Or use the Read tool with Read(//etc/hosts)",
        ]

    def test_outside_home_path_uses_tilde_read_rule(
        self,
        settings_files: list[Path],
        workdir: Path,
        skill_map: list[MatchingRule],
    ) -> None:
        result = _triage(
            target="rg allow ~/.claude/settings.json",
            settings_files=settings_files,
            workdir=workdir,
            skill_map=skill_map,
        )
        assert result.advice[-1] == "Or use the Read tool with Read(~/.claude/settings.json)"

    def test_reports_files_lacking_rule(
        self,
        tmp_path: Path,
        project_settings: Path,
        workdir: Path,
        skill_map: list[MatchingRule],
    ) -> None:
        covered = _settings(tmp_path / "covered" / "settings.local.json", allow=["Bash(make:*)"])
        result = _triage(
            target="make test",
            settings_files=[project_settings, covered],
            workdir=workdir,
            skill_map=skill_map,
        )
        assert result.files_missing == [project_settings]

    def test_already_allowed_everywhere(
        self,
        tmp_path: Path,
        workdir: Path,
        skill_map: list[MatchingRule],
    ) -> None:
        covered = _settings(tmp_path / "a" / "settings.local.json", allow=["Bash(make:*)"])
        result = _triage(
            target="make test",
            settings_files=[covered],
            workdir=workdir,
            skill_map=skill_map,
        )
        assert result.verdict is Verdict.ALREADY_ALLOWED

    @pytest.mark.parametrize(
        "content",
        [
            b"{not json",
            b"\xff\xfe not utf-8",
            b"[1, 2]",
            b'{"permissions": []}',
            b'{"permissions": "x"}',
        ],
    )
    def test_unusable_settings_are_reported_not_targeted(
        self,
        content: bytes,
        tmp_path: Path,
        project_settings: Path,
        workdir: Path,
        skill_map: list[MatchingRule],
    ) -> None:
        broken = tmp_path / "broken.json"
        broken.write_bytes(content)
        result = _triage(
            target="make test",
            settings_files=[project_settings, broken],
            workdir=workdir,
            skill_map=skill_map,
        )
        assert (result.files_missing, result.files_unreadable, result.advice) == (
            [project_settings],
            [broken],
            [f"Repair or remove unreadable settings file {broken}"],
        )

    def test_non_list_rule_entries_are_ignored(
        self,
        tmp_path: Path,
        workdir: Path,
        skill_map: list[MatchingRule],
    ) -> None:
        odd = tmp_path / "odd.json"
        odd.write_text(json.dumps({"permissions": {"allow": "Bash(make:*)", "deny": 3}}))
        result = _triage(
            target="make test",
            settings_files=[odd],
            workdir=workdir,
            skill_map=skill_map,
        )
        assert result.verdict is Verdict.GRANT

    def test_real_skill_map_routes_pr_view(
        self,
        settings_files: list[Path],
        workdir: Path,
    ) -> None:
        result = mod.triage(
            target="gh pr view 12",
            settings_files=settings_files,
            working_dirs=[workdir],
        )
        assert result.verdict is Verdict.USE_ALTERNATIVE

    def test_to_dict_is_wire_safe(
        self,
        settings_files: list[Path],
        workdir: Path,
        skill_map: list[MatchingRule],
    ) -> None:
        result = _triage(
            target="make test",
            settings_files=settings_files,
            workdir=workdir,
            skill_map=skill_map,
        )
        assert result.to_dict() == {
            "target": "make test",
            "verdict": "grant",
            "rule": "Bash(make:*)",
            "reason": "No better fix applies; 2 settings file(s) lack the rule.",
            "advice": [],
            "files_missing": [str(path) for path in settings_files],
            "files_unreadable": [],
        }


class TestGrantEverywhere:
    def test_writes_rule_to_every_file(
        self,
        settings_files: list[Path],
        workdir: Path,
        skill_map: list[MatchingRule],
    ) -> None:
        mod.grant_everywhere(
            target="make test",
            settings_files=settings_files,
            working_dirs=[workdir],
            skill_map_rules=skill_map,
        )
        assert [_allow(path) for path in settings_files] == [["Bash(make:*)"], ["Bash(make:*)"]]

    def test_reports_granted_files(
        self,
        settings_files: list[Path],
        workdir: Path,
        skill_map: list[MatchingRule],
    ) -> None:
        result = mod.grant_everywhere(
            target="make test",
            settings_files=settings_files,
            working_dirs=[workdir],
            skill_map_rules=skill_map,
        )
        assert isinstance(result, SuccessResult)
        assert result.value["granted"] == [str(path) for path in settings_files]

    def test_dry_run_writes_nothing(
        self,
        settings_files: list[Path],
        workdir: Path,
        skill_map: list[MatchingRule],
    ) -> None:
        mod.grant_everywhere(
            target="make test",
            settings_files=settings_files,
            working_dirs=[workdir],
            skill_map_rules=skill_map,
            dry_run=True,
        )
        assert [_allow(path) for path in settings_files] == [[], []]

    def test_refuses_non_grant_verdict(
        self,
        settings_files: list[Path],
        workdir: Path,
        skill_map: list[MatchingRule],
    ) -> None:
        result = mod.grant_everywhere(
            target="git status && git log",
            settings_files=settings_files,
            working_dirs=[workdir],
            skill_map_rules=skill_map,
        )
        assert isinstance(result, ErrorResult)
        assert result.details["triage"]["verdict"] == "normalize"

    def test_refusal_leaves_files_untouched(
        self,
        settings_files: list[Path],
        workdir: Path,
        skill_map: list[MatchingRule],
    ) -> None:
        mod.grant_everywhere(
            target="cat ~/.aws/credentials",
            settings_files=settings_files,
            working_dirs=[workdir],
            skill_map_rules=skill_map,
        )
        assert [_allow(path) for path in settings_files] == [[], []]

    def test_redirects_tracked_settings_json(
        self,
        monkeypatch: pytest.MonkeyPatch,
        workdir: Path,
        skill_map: list[MatchingRule],
    ) -> None:
        tracked = _settings(workdir / ".claude" / "settings.json")
        local = _settings(workdir / ".claude" / "settings.local.json")
        monkeypatch.setattr(catalog_write, "_is_git_tracked", lambda path: path == tracked)
        mod.grant_everywhere(
            target="make test",
            settings_files=[tracked],
            working_dirs=[workdir],
            skill_map_rules=skill_map,
        )
        assert (_allow(tracked), _allow(local)) == ([], ["Bash(make:*)"])

    def test_skips_redirect_target_already_covered(
        self,
        monkeypatch: pytest.MonkeyPatch,
        workdir: Path,
        skill_map: list[MatchingRule],
    ) -> None:
        tracked = _settings(workdir / ".claude" / "settings.json")
        local = _settings(workdir / ".claude" / "settings.local.json", allow=["Bash(make:*)"])
        monkeypatch.setattr(catalog_write, "_is_git_tracked", lambda path: path == tracked)
        result = mod.grant_everywhere(
            target="make test",
            settings_files=[tracked],
            working_dirs=[workdir],
            skill_map_rules=skill_map,
        )
        assert isinstance(result, SuccessResult)
        assert (result.value["granted"], _allow(local)) == ([], ["Bash(make:*)"])

    def test_creates_missing_permissions_block(
        self,
        tmp_path: Path,
        workdir: Path,
        skill_map: list[MatchingRule],
    ) -> None:
        bare = tmp_path / "bare" / "settings.local.json"
        bare.parent.mkdir()
        bare.write_text("{}")
        mod.grant_everywhere(
            target="mcp__plugin_dev10x_cli__pr_get",
            settings_files=[bare],
            working_dirs=[workdir],
            skill_map_rules=skill_map,
        )
        assert _allow(bare) == ["mcp__plugin_dev10x_cli__pr_get"]

    def test_write_failure_is_reported_and_others_still_granted(
        self,
        monkeypatch: pytest.MonkeyPatch,
        global_settings: Path,
        project_settings: Path,
        workdir: Path,
        skill_map: list[MatchingRule],
    ) -> None:
        real_append = mod._append_allow

        def flaky_append(*, path: Path, rule: str) -> None:
            if path == global_settings:
                raise OSError("disk full")
            real_append(path=path, rule=rule)

        monkeypatch.setattr(mod, "_append_allow", flaky_append)
        result = mod.grant_everywhere(
            target="make test",
            settings_files=[global_settings, project_settings],
            working_dirs=[workdir],
            skill_map_rules=skill_map,
        )
        assert isinstance(result, ErrorResult)
        assert (result.details["failed"], result.details["granted"]) == (
            [str(global_settings)],
            [str(project_settings)],
        )

    def test_unreadable_redirect_target_is_reported(
        self,
        monkeypatch: pytest.MonkeyPatch,
        workdir: Path,
        skill_map: list[MatchingRule],
    ) -> None:
        tracked = _settings(workdir / ".claude" / "settings.json")
        local = workdir / ".claude" / "settings.local.json"
        local.write_text("{not json")
        monkeypatch.setattr(catalog_write, "_is_git_tracked", lambda path: path == tracked)
        result = mod.grant_everywhere(
            target="make test",
            settings_files=[tracked],
            working_dirs=[workdir],
            skill_map_rules=skill_map,
            dry_run=True,
        )
        assert isinstance(result, ErrorResult)
        assert result.details["failed"] == [str(local)]
