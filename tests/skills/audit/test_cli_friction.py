"""Tests for the CLI-friction scanner (GH-5)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.skills.audit import cli_friction as mod


def _write(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return path


@pytest.fixture
def skill_root(tmp_path: Path) -> Path:
    """A throwaway ``skills/`` root for fixture files."""
    root = tmp_path / "skills"
    root.mkdir()
    return root


class TestRulesMatchRawCommands:
    """Each rule fires on the canonical raw-command form."""

    @pytest.mark.parametrize(
        ("rule_id", "line"),
        [
            ("raw-gh-pr", "gh pr view 42 --json title"),
            ("raw-gh-pr", "$ gh pr list --state open"),
            ("raw-gh-issue", "gh issue create --title foo"),
            ("raw-gh-api", "gh api repos/owner/repo/pulls/42/comments"),
            ("raw-gh-repo", "gh repo view --json nameWithOwner"),
            ("raw-git-commit", "git commit -m 'msg'"),
            ("raw-git-push", "git push --force-with-lease origin foo"),
            ("raw-git-rebase", "git rebase -i develop"),
            ("raw-git-branch", "git checkout -b user/PROJ-1/slug"),
            ("raw-pytest", "pytest src/"),
            ("raw-pytest", "uv run pytest --cov"),
            ("raw-pytest", "python -m pytest"),
            ("no-verify", "git commit --no-verify -m 'rebase'"),
        ],
    )
    def test_rule_fires_for_canonical_command(
        self, skill_root: Path, rule_id: str, line: str
    ) -> None:
        skill = _write(
            skill_root / "demo" / "SKILL.md",
            "# Demo\n\n```bash\n" + line + "\n```\n",
        )
        violations = mod.scan_file(skill)
        rule_ids = {v.rule.rule_id for v in violations}
        assert rule_id in rule_ids


class TestRulesIgnoreProse:
    """Rule patterns ignore lines outside fenced bash blocks in Markdown."""

    @pytest.mark.parametrize(
        "line",
        [
            "We previously used `gh pr view` — now use the MCP tool.",
            "| Run tests | `Skill(test)` | `pytest`, `uv run pytest` |",
            "Avoid running `git commit` directly.",
            "Never use `gh api` from inside a skill body.",
        ],
    )
    def test_prose_mentions_are_ignored(self, skill_root: Path, line: str) -> None:
        skill = _write(skill_root / "demo" / "SKILL.md", "# Demo\n\n" + line + "\n")
        assert mod.scan_file(skill) == []

    def test_non_bash_fence_is_ignored(self, skill_root: Path) -> None:
        skill = _write(
            skill_root / "demo" / "SKILL.md",
            "# Demo\n\n```python\nsubprocess.run(['gh', 'pr', 'view'])\n```\n",
        )
        assert mod.scan_file(skill) == []

    def test_frontmatter_is_ignored(self, skill_root: Path) -> None:
        skill = _write(
            skill_root / "demo" / "SKILL.md",
            "---\nname: Dev10x:demo\nallowed-tools:\n  - Bash(git commit:*)\n---\n",
        )
        assert mod.scan_file(skill) == []


class TestWriteGuardClaude:
    """GH-817 (ADR-0018): forbid runtime Write/Edit(.claude/**) in skill docs.

    Unlike the CLI rules, this one is scanned in PROSE (not only shell
    fences) — a skill doc instructing a `.claude/` write is prose, not a
    shell command.
    """

    @pytest.mark.parametrize(
        "line",
        [
            "Persist via `Write(.claude/Dev10x/session.yaml)` on adoption.",
            "Then `Edit(.claude/settings.local.json)` to add the rule.",
            'Call Write(file_path=".claude/Dev10x/config.yaml").',
            "Use MultiEdit(.claude/Dev10x/session.yaml) for both keys.",
        ],
    )
    def test_flags_write_edit_under_claude_in_prose(self, skill_root: Path, line: str) -> None:
        skill = _write(skill_root / "demo" / "SKILL.md", "# Demo\n\n" + line + "\n")
        rule_ids = {v.rule.rule_id for v in mod.scan_file(skill)}
        assert "write-guard-claude" in rule_ids

    @pytest.mark.parametrize(
        "line",
        [
            # Describing a path (backticked, no Write/Edit call) is fine.
            "The file `.claude/Dev10x/config.yaml` holds durable prefs.",
            "Do NOT Write/Edit `.claude/**` at runtime.",
            # A write to a non-.claude path is out of scope.
            "Call `Write(/tmp/Dev10x/commit-msg.txt)` for the message.",
            "Use `Write(~/.config/Dev10x/friction.yaml)` — outside the repo.",
        ],
    )
    def test_ignores_path_mentions_and_non_claude_writes(
        self, skill_root: Path, line: str
    ) -> None:
        skill = _write(skill_root / "demo" / "SKILL.md", "# Demo\n\n" + line + "\n")
        rule_ids = {v.rule.rule_id for v in mod.scan_file(skill)}
        assert "write-guard-claude" not in rule_ids

    def test_inline_allow_silences_the_guard(self, skill_root: Path) -> None:
        skill = _write(
            skill_root / "demo" / "SKILL.md",
            "# Demo\n\nWrite(.claude/Dev10x/x.yaml) "
            "<!-- cli-friction: allow write-guard-claude — legacy example -->\n",
        )
        rule_ids = {v.rule.rule_id for v in mod.scan_file(skill)}
        assert "write-guard-claude" not in rule_ids

    def test_meta_doc_skill_is_exempt(self, skill_root: Path) -> None:
        # diag-friction quotes the bad pattern back at the agent.
        skill = _write(
            skill_root / "diag-friction" / "SKILL.md",
            "# Anti-pattern\n\nNever do `Write(.claude/Dev10x/session.yaml)`.\n",
        )
        rule_ids = {v.rule.rule_id for v in mod.scan_file(skill)}
        assert "write-guard-claude" not in rule_ids

    def test_frontmatter_is_ignored(self, skill_root: Path) -> None:
        skill = _write(
            skill_root / "demo" / "SKILL.md",
            "---\nname: Dev10x:demo\ndesc: Write(.claude/x.yaml) in meta\n---\n\nBody.\n",
        )
        rule_ids = {v.rule.rule_id for v in mod.scan_file(skill)}
        assert "write-guard-claude" not in rule_ids


class TestSkillExemptions:
    """Skills that implement the underlying op are exempt from their rules."""

    @pytest.mark.parametrize(
        ("skill_name", "rule_id", "line"),
        [
            ("git-commit", "raw-git-commit", "git commit -m 'msg'"),
            ("git-groom", "raw-git-rebase", "git rebase -i develop"),
            ("git", "raw-git-push", "git push --force-with-lease"),
            ("ticket-branch", "raw-git-branch", "git checkout -b user/X/slug"),
            ("gh-pr-respond", "raw-gh-api", "gh api repos/o/r/pulls/comments"),
            ("py-test", "raw-pytest", "pytest --cov"),
        ],
    )
    def test_implementer_skill_is_exempt(
        self, skill_root: Path, skill_name: str, rule_id: str, line: str
    ) -> None:
        skill = _write(
            skill_root / skill_name / "SKILL.md",
            "# X\n\n```bash\n" + line + "\n```\n",
        )
        rule_ids = {v.rule.rule_id for v in mod.scan_file(skill)}
        assert rule_id not in rule_ids

    def test_no_verify_has_no_exemptions(self, skill_root: Path) -> None:
        skill = _write(
            skill_root / "git-commit" / "SKILL.md",
            "# X\n\n```bash\ngit commit --no-verify -m foo\n```\n",
        )
        rule_ids = {v.rule.rule_id for v in mod.scan_file(skill)}
        assert "no-verify" in rule_ids


class TestInlineAllow:
    """Per-line opt-out marker silences specific rules on that line."""

    def test_inline_allow_silences_named_rule(self, skill_root: Path) -> None:
        skill = _write(
            skill_root / "demo" / "SKILL.md",
            (
                "# X\n\n"
                "```bash\n"
                "git commit -m foo  # cli-friction: allow raw-git-commit — example only\n"
                "```\n"
            ),
        )
        assert mod.scan_file(skill) == []

    def test_inline_allow_does_not_silence_other_rules(self, skill_root: Path) -> None:
        skill = _write(
            skill_root / "demo" / "SKILL.md",
            (
                "# X\n\n"
                "```bash\n"
                "git commit --no-verify  # cli-friction: allow raw-git-commit\n"
                "```\n"
            ),
        )
        rule_ids = {v.rule.rule_id for v in mod.scan_file(skill)}
        assert rule_ids == {"no-verify"}


class TestYamlScanning:
    """Playbook YAML files are scanned regardless of fence context."""

    def test_yaml_prompt_with_raw_command_is_flagged(self, skill_root: Path) -> None:
        playbook = _write(
            skill_root / "demo" / "references" / "playbook.yaml",
            "defaults:\n  feature:\n    steps:\n"
            "      - prompt: Run pytest with coverage. Fix failures.\n",
        )
        rule_ids = {v.rule.rule_id for v in mod.scan_file(playbook)}
        assert "raw-pytest" in rule_ids

    def test_yaml_block_scalar_prose_is_ignored(self, skill_root: Path) -> None:
        playbook = _write(
            skill_root / "demo" / "references" / "playbook.yaml",
            (
                "defaults:\n"
                "  bugfix:\n"
                "    checks:\n"
                "      - prompt: >\n"
                "          Were tests delegated to the test skill (not raw\n"
                "          pytest/uv run pytest)? Were commits via\n"
                "          Dev10x:git-commit (not raw git commit)?\n"
                "      - check: gh pr checks {pr_number}\n"
            ),
        )
        violations = mod.scan_file(playbook)
        # The block-scalar prose should not fire any rule, but the literal
        # ``check: gh pr checks`` value should still be flagged.
        rule_ids = [v.rule.rule_id for v in violations]
        assert rule_ids == ["raw-gh-pr"]
        assert violations[0].line_no == 8


class TestFindTargetFiles:
    """``find_target_files`` walks a skills root and returns doc files."""

    def test_returns_skill_md_and_instructions_md(self, skill_root: Path) -> None:
        _write(skill_root / "a" / "SKILL.md", "")
        _write(skill_root / "a" / "instructions.md", "")
        _write(skill_root / "a" / "references" / "playbook.yaml", "")
        _write(skill_root / "a" / "references" / "guide.md", "")
        files = {p.name for p in mod.find_target_files(skill_root)}
        assert files == {"SKILL.md", "instructions.md", "playbook.yaml", "guide.md"}

    def test_excludes_scripts_and_evals(self, skill_root: Path) -> None:
        _write(skill_root / "a" / "scripts" / "run.sh", "")
        _write(skill_root / "a" / "evals" / "evals.json", "")
        _write(skill_root / "a" / "SKILL.md", "")
        files = mod.find_target_files(skill_root)
        assert [p.name for p in files] == ["SKILL.md"]

    def test_returns_empty_for_missing_root(self, tmp_path: Path) -> None:
        assert mod.find_target_files(tmp_path / "nonexistent") == []


class TestScanPaths:
    """``scan_paths`` aggregates violations across files."""

    def test_aggregates_across_files(self, skill_root: Path) -> None:
        a = _write(
            skill_root / "demo-a" / "SKILL.md",
            "# A\n\n```bash\ngit commit -m foo\n```\n",
        )
        b = _write(
            skill_root / "demo-b" / "SKILL.md",
            "# B\n\n```bash\npytest src/\n```\n",
        )
        violations = mod.scan_paths([a, b])
        assert len(violations) == 2
        assert {v.rule.rule_id for v in violations} == {"raw-git-commit", "raw-pytest"}

    def test_skips_missing_paths(self, skill_root: Path) -> None:
        assert mod.scan_paths([skill_root / "missing.md"]) == []


class TestViolationFormat:
    """``Violation.format`` produces a reviewer-friendly message."""

    def test_includes_path_line_rule_and_suggestion(self, skill_root: Path) -> None:
        skill = _write(
            skill_root / "demo" / "SKILL.md",
            "# X\n\n```bash\ngit commit -m foo\n```\n",
        )
        v = mod.scan_file(skill)[0]
        formatted = v.format()
        assert str(skill) in formatted
        assert "[raw-git-commit]" in formatted
        assert "git commit -m foo" in formatted
        assert "Skill(Dev10x:git-commit)" in formatted
