"""End-to-end smoke tests integrating SKILL.md orchestration with the
diag-friction analyzers (GH-247 finding G7).

Coverage goal: verify that the two runtime data sources the skill reads
during Step 2 and Step 3c-pre are internally consistent and route
representative friction-causing commands to the documented skills/tools
exactly as the SKILL.md orchestration prescribes.

What is NOT covered here (already covered in other suites):
- cli_friction.scan_file / scan_paths / find_target_files   → test_cli_friction.py
- structured-alternatives KB schema validation              → test_structured_alternatives.py

What IS added here:
- Command-skill-map.yaml: prefix-match routing (Step 2) for canonical
  friction commands → expected skill / tool
- Inline-code path (Step 3c-pre): end-to-end prefix detection +
  keyword-match → structured-tool recommendation
- META_DOC_SKILLS exemption: diag-friction's own SKILL.md is exempt from
  the cli-friction scanner (it quotes bad commands deliberately)
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="pyyaml not installed")

from dev10x.skills.audit import cli_friction as cli_friction_mod  # noqa: E402

# ── Paths to canonical data files ────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MAP_PATH = _REPO_ROOT / "src" / "dev10x" / "validators" / "command-skill-map.yaml"
_SA_PATH = _REPO_ROOT / "skills" / "diag-friction" / "references" / "structured-alternatives.yaml"
_SKILL_MD_PATH = _REPO_ROOT / "skills" / "diag-friction" / "SKILL.md"


# ── Shared fixtures ───────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def command_map() -> dict:
    return yaml.safe_load(_MAP_PATH.read_text())


@pytest.fixture(scope="module")
def sa_kb() -> dict:
    return yaml.safe_load(_SA_PATH.read_text())


# ── Helpers that replicate the SKILL.md matching algorithms ──────────────────


def _match_command_to_rule(command: str, rules: list[dict]) -> dict | None:
    """Replicate the Step 2 prefix-match algorithm documented in SKILL.md.

    "Match the identified command against the patterns list in each mapping
    entry.  Use prefix matching — if the command starts with any pattern in
    the list, it matches that entry."

    Returns the first matching rule dict, or None when no rule matches.
    """
    for rule in rules:
        if rule.get("matcher") != "Bash":
            continue
        for pattern in rule.get("patterns", []):
            if command.startswith(pattern):
                return rule
    return None


def _match_inline_code_keyword(body: str, alternatives: list[dict]) -> str | None:
    """Replicate the Step 3c-pre keyword-match algorithm.

    "Match the body against each entry's detection_keywords (substring match;
    first hit wins)."

    Returns the matched tool string, or the fallback tool when no keyword
    matches.
    """
    for entry in alternatives:
        for keyword in entry["detection_keywords"]:
            if keyword in body:
                return entry["tool"]
    # Fallback: empty detection_keywords entry
    for entry in alternatives:
        if entry["detection_keywords"] == []:
            return entry["tool"]
    return None


# ── Step 2: command-skill-map routing (representative friction commands) ──────


class TestCommandSkillMapRouting:
    """Step 2 prefix-match routes friction commands to the documented skill/tool.

    Each scenario drives the same algorithm the skill uses at runtime so a
    map regression (entry deleted, pattern renamed) surfaces here immediately.
    """

    @pytest.mark.parametrize(
        ("command", "expected_compensation_type", "expected_target"),
        [
            # Bash hard-block rules → use-skill
            ("git commit -m 'Enable X'", "use-skill", "Dev10x:git-commit"),
            ("gh pr create --title 'Enable X'", "use-skill", "Dev10x:gh-pr-create"),
            ("gh pr merge --squash", "use-skill", "Dev10x:gh-pr-merge"),
            ("git push origin feature-branch", "use-skill", "Dev10x:git"),
            ("git rebase -i develop", "use-skill", "Dev10x:git-groom"),
            ("gh pr checks --watch", "use-skill", "Dev10x:gh-pr-monitor"),
            # Bash hard-block rules → use-tool
            ("gh pr view 42", "use-tool", "mcp__plugin_Dev10x_cli__pr_get"),
            ("gh issue close 123", "use-tool", "mcp__plugin_Dev10x_cli__issue_close"),
            ("gh issue reopen 99", "use-tool", "mcp__plugin_Dev10x_cli__issue_reopen"),
            ("gh issue view 7", "use-tool", "mcp__plugin_Dev10x_cli__issue_get"),
            (
                "gh issue create --title x",
                "use-tool",
                "mcp__plugin_Dev10x_cli__issue_create",
            ),
            ("gh pr edit --title y", "use-tool", "mcp__plugin_Dev10x_cli__update_pr"),
            (
                "gh issue edit 5 --title z",
                "use-tool",
                "mcp__plugin_Dev10x_cli__issue_edit",
            ),
            (
                "gh issue comment 3 --body hi",
                "use-tool",
                "mcp__plugin_Dev10x_cli__issue_comment",
            ),
        ],
    )
    def test_command_routes_to_expected_target(
        self,
        command: str,
        expected_compensation_type: str,
        expected_target: str,
        command_map: dict,
    ) -> None:
        rules = command_map["rules"]
        matched_rule = _match_command_to_rule(command=command, rules=rules)

        assert matched_rule is not None, (
            f"Command {command!r} matched no rule — map entry may be missing or renamed"
        )

        compensations = matched_rule.get("compensations", [])
        assert compensations, f"Rule {matched_rule['name']!r} has no compensations"

        # First compensation is documented as the recommended path
        first = compensations[0]
        assert first["type"] == expected_compensation_type, (
            f"Rule {matched_rule['name']!r}: expected type {expected_compensation_type!r}, "
            f"got {first['type']!r}"
        )

        target_key = "skill" if expected_compensation_type == "use-skill" else "tool"
        assert first[target_key] == expected_target, (
            f"Rule {matched_rule['name']!r}: expected {target_key}={expected_target!r}, "
            f"got {first.get(target_key)!r}"
        )

    def test_unrecognised_command_returns_no_match(self, command_map: dict) -> None:
        """Step 2 falls through to Step 3 when no rule matches."""
        rules = command_map["rules"]
        result = _match_command_to_rule(
            command="some-totally-unknown-cli-tool --flag",
            rules=rules,
        )
        assert result is None

    def test_map_has_config_and_rules_sections(self, command_map: dict) -> None:
        assert "config" in command_map, "command-skill-map.yaml missing 'config' section"
        assert "rules" in command_map, "command-skill-map.yaml missing 'rules' section"
        assert isinstance(command_map["rules"], list)
        assert len(command_map["rules"]) > 0

    def test_every_bash_rule_has_name_patterns_compensations(self, command_map: dict) -> None:
        for rule in command_map["rules"]:
            if rule.get("matcher") != "Bash":
                continue
            assert "name" in rule, f"Bash rule missing 'name': {rule}"
            assert "patterns" in rule, f"Rule {rule['name']!r} missing 'patterns'"
            assert isinstance(rule["patterns"], list) and rule["patterns"]
            assert "compensations" in rule, f"Rule {rule['name']!r} missing 'compensations'"
            assert rule["compensations"], f"Rule {rule['name']!r} has empty compensations"


# ── Step 3c-pre: inline-code → structured-alternative routing ────────────────


class TestInlineCodeStructuredAlternativeRouting:
    """Step 3c-pre: prefix detection + keyword-match → structured tool.

    End-to-end path: command starts with an inline-code prefix (Step 3c-pre
    guard), then the body is keyword-matched to the canonical tool.
    """

    @pytest.mark.parametrize(
        ("command", "expected_tool"),
        [
            # Each command must (a) begin with an inline-code prefix,
            # (b) have a body whose keywords match a KB entry.
            (
                "python3 -c \"import json; json.loads(open('x.json').read())\"",
                "jq",
            ),
            (
                "python -c \"import yaml; yaml.safe_load(open('x.yml'))\"",
                "yq",
            ),
            (
                "sh -c \"import requests; requests.get('https://api.example.com/data')\"",
                "curl",
            ),
            (
                "node -e \"const d = JSON.parse(fs.readFileSync('x.json'))\"",
                "jq",
            ),
            (
                "bash -c \"import tomllib; tomllib.loads(open('p.toml').read())\"",
                "tomlq",
            ),
        ],
    )
    def test_inline_command_surfaces_structured_alternative(
        self,
        command: str,
        expected_tool: str,
        sa_kb: dict,
    ) -> None:
        prefixes: list[str] = sa_kb["inline_code_prefixes"]
        alternatives: list[dict] = sa_kb["alternatives"]

        # Guard: command starts with a recognised inline-code prefix
        matched_prefix = next(
            (p for p in prefixes if command.startswith(p)),
            None,
        )
        assert matched_prefix is not None, (
            f"Command {command!r} did not start with any inline_code_prefix — "
            f"test setup error or KB prefix missing"
        )

        # Extract body (everything after the prefix)
        body = command[len(matched_prefix) :].strip().strip("\"'")

        matched_tool = _match_inline_code_keyword(body=body, alternatives=alternatives)
        assert matched_tool == expected_tool, (
            f"Command {command!r}: expected tool {expected_tool!r}, got {matched_tool!r}"
        )

    def test_unrecognised_body_falls_back_to_tools_extraction(self, sa_kb: dict) -> None:
        """Fallback entry ensures no command is left without a recommendation."""
        body = "completely_unknown_bespoke_function_xyz()"
        result = _match_inline_code_keyword(
            body=body,
            alternatives=sa_kb["alternatives"],
        )
        assert result is not None
        assert "tools" in result or "~/.claude" in result


# ── META_DOC_SKILLS exemption: diag-friction SKILL.md itself ─────────────────


class TestDiagFrictionSkillMdExemption:
    """The diag-friction SKILL.md is exempt from the cli-friction scanner.

    The skill quotes raw CLI commands back to the agent as cautionary
    examples.  cli_friction.META_DOC_SKILLS must include 'diag-friction'
    so the scanner does not flag these intentional quotes.
    """

    def test_diag_friction_in_meta_doc_skills(self) -> None:
        assert "diag-friction" in cli_friction_mod.META_DOC_SKILLS

    def test_skill_md_produces_no_violations(self) -> None:
        assert _SKILL_MD_PATH.is_file(), f"SKILL.md missing at {_SKILL_MD_PATH}"
        violations = cli_friction_mod.scan_file(path=_SKILL_MD_PATH)
        assert violations == [], (
            "diag-friction SKILL.md should be exempt from cli-friction scanner — "
            f"unexpected violations: {[v.format() for v in violations]}"
        )

    def test_meta_doc_skills_exemption_covers_raw_command_rules(self) -> None:
        """Rules that scan for raw CLI commands must exempt META_DOC_SKILLS.

        'no-verify' is deliberately global (no exemptions) — that rule is
        about --no-verify in commits, not quoting bad commands.  All other
        rules that scan for raw gh/git/pytest commands must include
        'diag-friction' so the skill can quote those commands as examples.
        """
        rules_requiring_exemption = {
            "raw-gh-pr",
            "raw-gh-issue",
            "raw-gh-api",
            "raw-gh-repo",
            "raw-git-commit",
            "raw-git-push",
            "raw-git-rebase",
            "raw-git-branch",
            "raw-pytest",
        }
        for rule_id in rules_requiring_exemption:
            exempt_set = cli_friction_mod.SKILL_EXEMPTIONS.get(rule_id, frozenset())
            assert "diag-friction" in exempt_set, (
                f"Rule {rule_id!r} does not exempt 'diag-friction' via META_DOC_SKILLS"
            )
