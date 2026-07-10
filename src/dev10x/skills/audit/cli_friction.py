"""Detect raw CLI commands in skill docs that should route through MCP/Skill wrappers.

Background: skill docs (`SKILL.md`, `instructions.md`, `references/*.md`,
`references/*.yaml`) sometimes embed example commands like ``gh pr view``,
``git commit``, or ``pytest`` directly. Two failure modes follow:

1. **Permission friction** — every raw ``gh``/``git``/``pytest`` invocation
   needs a matching ``Bash(...:*)`` allow rule in front matter, otherwise
   users hit an approval prompt on every run.
2. **Guardrail bypass** — the agent reads the example and runs the raw
   command instead of the project's ``Skill(...)`` wrapper, skipping
   gitmoji/JTBD/CI-monitor/coverage gates that the wrapper enforces.

This module scans skill docs and reports each raw CLI usage with the
suggested replacement. Only fenced code blocks tagged ``bash``, ``sh``,
or ``shell`` are scanned — prose tables that *describe* what to avoid
are left alone.

Skills whose job is to *implement* the underlying operation (e.g.,
``git-commit`` implements ``git commit``) are exempt via :data:`SKILL_EXEMPTIONS`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# ── Skills allowed to embed raw operations (they ARE the wrapper) ──────
GIT_IMPLEMENTERS = frozenset(
    {
        "git",
        "git-alias-setup",
        "git-commit",
        "git-commit-split",
        "git-fixup",
        "git-groom",
        "git-promote",
        "git-worktree",
        "ticket-branch",
    }
)
GH_IMPLEMENTERS = frozenset(
    {
        "gh-context",
        "gh-pr-bookmark",
        "gh-pr-create",
        "gh-pr-doctor",
        "gh-pr-fixup",
        "gh-pr-merge",
        "gh-pr-monitor",
        "gh-pr-request-review",
        "gh-pr-respond",
        "gh-pr-review",
        "gh-pr-triage",
        "request-review",
    }
)
# Skills whose docs intentionally embed raw CLI as the *thing being warned
# against* — e.g., `diag-friction` quotes the bad command back to the
# agent so it learns to avoid it.
META_DOC_SKILLS = frozenset({"diag-friction"})
PYTEST_IMPLEMENTERS = frozenset({"py-test", "py-test-flaky"})

# Skills exempt from each rule family. Maps rule_id → set of skill dir names.
SKILL_EXEMPTIONS: dict[str, frozenset[str]] = {
    "raw-gh-pr": GH_IMPLEMENTERS | META_DOC_SKILLS,
    "raw-gh-issue": GH_IMPLEMENTERS | META_DOC_SKILLS | frozenset({"ticket-create", "park"}),
    "raw-gh-api": GH_IMPLEMENTERS | META_DOC_SKILLS,
    "raw-gh-repo": GH_IMPLEMENTERS | META_DOC_SKILLS,
    "raw-git-commit": GIT_IMPLEMENTERS | META_DOC_SKILLS,
    "raw-git-push": GIT_IMPLEMENTERS | META_DOC_SKILLS,
    "raw-git-rebase": GIT_IMPLEMENTERS | META_DOC_SKILLS,
    "raw-git-branch": GIT_IMPLEMENTERS | META_DOC_SKILLS,
    "raw-pytest": PYTEST_IMPLEMENTERS | META_DOC_SKILLS | frozenset({"gh-pr-create"}),
    "no-verify": frozenset(),
    # diag-friction quotes the bad `Write(.claude/…)` pattern back at the
    # agent as the thing to avoid, so it is exempt from the write guard.
    "write-guard-claude": META_DOC_SKILLS,
}


@dataclass(frozen=True)
class Rule:
    """A single CLI-friction detection rule."""

    rule_id: str
    pattern: re.Pattern[str]
    message: str
    suggestion: str


# Patterns target the START of a shell command. Anchors: start-of-line,
# whitespace, common shell separators (``;``/``|``/``&``), backtick, or
# ``$(`` (command substitution). Plain ``(`` is excluded so prose like
# "(not raw pytest)" does not match.
_CMD_START = r"(?:^|[\s;&|`]|\$\()"

RULES: tuple[Rule, ...] = (
    Rule(
        rule_id="raw-gh-pr",
        pattern=re.compile(
            _CMD_START + r"gh\s+pr\s+(?:view|list|checks|ready|comment|create|edit|merge|diff)\b"
        ),
        message="Raw `gh pr ...` command in skill doc",
        suggestion=(
            "Use `mcp__plugin_Dev10x_cli__pr_detect` / `pr_comments` / "
            "`verify_pr_state` / `Skill(Dev10x:gh-pr-*)` instead"
        ),
    ),
    Rule(
        rule_id="raw-gh-issue",
        pattern=re.compile(_CMD_START + r"gh\s+issue\s+(?:view|list|create|comment|edit|close)\b"),
        message="Raw `gh issue ...` command in skill doc",
        suggestion=(
            "Use `mcp__plugin_Dev10x_cli__issue_get` / `issue_comments` / `issue_create` instead"
        ),
    ),
    Rule(
        rule_id="raw-gh-api",
        pattern=re.compile(_CMD_START + r"gh\s+api\b"),
        message="Raw `gh api` command in skill doc",
        suggestion=(
            "Use the matching `mcp__plugin_Dev10x_cli__*` tool when one exists "
            "(pr_comments, pr_comment_reply, issue_get, request_review, ...)"
        ),
    ),
    Rule(
        rule_id="raw-gh-repo",
        pattern=re.compile(_CMD_START + r"gh\s+repo\s+view\b"),
        message="Raw `gh repo view` command in skill doc",
        suggestion=(
            "Use `mcp__plugin_Dev10x_cli__pr_detect` (returns repo) or `detect_base_branch`"
        ),
    ),
    Rule(
        rule_id="raw-git-commit",
        # Match `git commit` but NOT `git commit -F <file>` inside our own
        # commit-message pattern (still flag — the wrapper still applies).
        pattern=re.compile(_CMD_START + r"git\s+commit\b"),
        message="Raw `git commit` command in skill doc",
        suggestion="Use `Skill(Dev10x:git-commit)` (or `Skill(Dev10x:git-fixup)` for fixups)",
    ),
    Rule(
        rule_id="raw-git-push",
        pattern=re.compile(_CMD_START + r"git\s+push\b"),
        message="Raw `git push` command in skill doc",
        suggestion="Use `Skill(Dev10x:git)` — enforces protected-branch checks",
    ),
    Rule(
        rule_id="raw-git-rebase",
        pattern=re.compile(_CMD_START + r"git\s+rebase\b"),
        message="Raw `git rebase` command in skill doc",
        suggestion=(
            "Use `Skill(Dev10x:git-groom)` for history rewrites, "
            "`Skill(Dev10x:git)` for unattended rebases"
        ),
    ),
    Rule(
        rule_id="raw-git-branch",
        pattern=re.compile(_CMD_START + r"git\s+checkout\s+-b\b"),
        message="Raw `git checkout -b` command in skill doc",
        suggestion="Use `Skill(Dev10x:ticket-branch)` (enforces username/TICKET-ID/slug naming)",
    ),
    Rule(
        rule_id="raw-pytest",
        pattern=re.compile(
            _CMD_START + r"(?:uv\s+run\s+(?:--[\w=-]+\s+)*)?(?:python\s+-m\s+)?pytest\b"
        ),
        message="Raw `pytest` invocation in skill doc",
        suggestion="Use `Skill(Dev10x:py-test)` — enforces coverage gate",
    ),
    Rule(
        rule_id="no-verify",
        pattern=re.compile(r"--no-verify\b"),
        message="`--no-verify` skips pre-commit hooks (CLAUDE.md global rule)",
        suggestion="Fix the underlying hook failure instead of bypassing it",
    ),
)

# Prose rules are scanned on EVERY doc line (outside front matter), not only
# inside shell fences: they target tool-call *instructions* written in prose
# (e.g. "Write the file to `.claude/Dev10x/session.yaml`"), not shell
# commands. Same `# cli-friction: allow <rule-id>` opt-out and
# SKILL_EXEMPTIONS apply.
PROSE_RULES: tuple[Rule, ...] = (
    Rule(
        rule_id="write-guard-claude",
        # Match a Write/Edit/MultiEdit tool call whose target path is under
        # a `.claude/` directory. Catches `Write(.claude/Dev10x/session.yaml)`
        # and `Edit(file_path="…/.claude/…")`. A bare backticked path in prose
        # (no `Write(`/`Edit(`) does not match — describing a path is fine;
        # instructing a runtime write to it is not.
        pattern=re.compile(r"\b(?:Write|Edit|MultiEdit)\([^)\n]*\.claude/"),
        message="Skill doc instructs a runtime Write/Edit under .claude/ (ADR-0018)",
        suggestion=(
            "Never Write/Edit `.claude/**` at runtime — it trips Claude Code's "
            "self-settings consent gate regardless of allow rules (GH-812). Route "
            "the write through an MCP/CLI writer (e.g. `dev10x session seed`) or "
            "keep the state outside the repo (`~/.config/Dev10x/…`)."
        ),
    ),
)

# Per-line opt-out marker. Place ``# cli-friction: allow <rule-id> — reason``
# at the end of the offending line to silence the scanner.
_INLINE_ALLOW = re.compile(r"(?:#|<!--)\s*cli-friction:\s*allow\s+(?P<rule>[\w,-]+)")
_FENCE_OPEN = re.compile(r"^\s*```(?P<lang>\w*)")
_FENCE_CLOSE = re.compile(r"^\s*```\s*$")
# Only fences explicitly tagged as a shell language are scanned. Untagged
# fences (``` ... ```) frequently hold output/example transcripts where
# the agent should NOT mistake the content for executable instructions.
_SCANNED_LANGS = frozenset({"bash", "sh", "shell", "console"})

# YAML block scalar opener — ``key: |`` or ``key: >`` (with optional
# chomping/indent indicators) starts an indented prose block.
_YAML_BLOCK_OPEN = re.compile(r":\s*[|>][+-]?\d*\s*$")


@dataclass(frozen=True)
class Violation:
    """A single rule hit in a skill file."""

    path: Path
    line_no: int
    line: str
    rule: Rule

    def format(self) -> str:
        return (
            f"{self.path}:{self.line_no}: [{self.rule.rule_id}] "
            f"{self.rule.message}\n"
            f"    | {self.line.rstrip()}\n"
            f"    → {self.rule.suggestion}"
        )


@dataclass
class _ScanState:
    in_fence: bool = False
    fence_lang: str = ""
    in_frontmatter: bool = False
    # YAML block scalar tracking — when active, ``yaml_block_indent`` is the
    # column at which the block's prose starts; lines indented further than
    # that are skipped. ``None`` means no active block.
    yaml_block_indent: int | None = None
    allowed_rules: set[str] = field(default_factory=set)


def _skill_dir_name(path: Path) -> str | None:
    """Return the skill directory name for a path under skills/<name>/, else None."""
    parts = path.parts
    try:
        idx = parts.index("skills")
    except ValueError:
        return None
    if idx + 1 >= len(parts):
        return None
    return parts[idx + 1]


def _is_exempt(rule: Rule, skill_name: str | None) -> bool:
    if skill_name is None:
        return False
    exempt = SKILL_EXEMPTIONS.get(rule.rule_id, frozenset())
    return skill_name in exempt


def _should_scan_line(line: str, state: _ScanState, path: Path) -> bool:
    """Decide whether to scan a single line for rule violations."""
    stripped = line.strip()

    # Track YAML front matter (skip it).
    if stripped == "---":
        if state.in_frontmatter:
            state.in_frontmatter = False
            return False
        # Front matter only opens at the very first non-empty line of the file;
        # we approximate by toggling on the first ``---``.
        if not state.in_fence:
            state.in_frontmatter = not state.in_frontmatter
            return False

    if state.in_frontmatter:
        return False

    # Track fenced code blocks.
    open_m = _FENCE_OPEN.match(line)
    if open_m and not state.in_fence:
        state.in_fence = True
        state.fence_lang = open_m.group("lang").lower()
        return False
    if _FENCE_CLOSE.match(line) and state.in_fence:
        state.in_fence = False
        state.fence_lang = ""
        return False

    # Markdown files: scan only inside fences explicitly tagged as a shell
    # language. Untagged fences usually hold output transcripts, not commands.
    if path.suffix == ".md":
        if not state.in_fence:
            return False
        return state.fence_lang in _SCANNED_LANGS

    # YAML files (e.g., playbook.yaml): skip indented prose inside block
    # scalars (``prompt: >`` / ``check: |``); scan everything else so command
    # values like ``check: gh pr checks`` are still flagged.
    if path.suffix in {".yaml", ".yml"}:
        if state.yaml_block_indent is not None:
            indent = len(line) - len(line.lstrip())
            if line.strip() == "" or indent >= state.yaml_block_indent:
                # Still inside the block scalar — skip.
                if _YAML_BLOCK_OPEN.search(line):
                    state.yaml_block_indent = indent + 2
                return False
            # De-dented past the scalar; resume scanning.
            state.yaml_block_indent = None
        if _YAML_BLOCK_OPEN.search(line):
            state.yaml_block_indent = len(line) - len(line.lstrip()) + 2
            # The opener line itself has no value — nothing to scan.
            return False
        return True
    return True


def scan_file(path: Path) -> list[Violation]:
    """Return all rule violations in a single skill doc."""
    if not path.is_file():
        return []

    skill_name = _skill_dir_name(path)
    content = path.read_text()
    state = _ScanState()
    violations: list[Violation] = []

    for line_no, line in enumerate(content.splitlines(), start=1):
        # Always call _should_scan_line so fence/front-matter state stays in
        # sync; its return only gates the fence-scoped CLI rules below.
        should_scan = _should_scan_line(line, state, path)

        # Per-line opt-out — comma-separated list of rule IDs.
        allow_match = _INLINE_ALLOW.search(line)
        allowed_here: set[str] = set()
        if allow_match:
            allowed_here = {r.strip() for r in allow_match.group("rule").split(",")}

        # Prose rules scan every line outside front matter — the pattern
        # targets tool-call instructions that may be plain prose, not just
        # shell-fenced commands.
        if not state.in_frontmatter:
            for rule in PROSE_RULES:
                if rule.rule_id in allowed_here or _is_exempt(rule, skill_name):
                    continue
                if rule.pattern.search(line):
                    violations.append(Violation(path=path, line_no=line_no, line=line, rule=rule))

        if not should_scan:
            continue

        for rule in RULES:
            if rule.rule_id in allowed_here:
                continue
            if _is_exempt(rule, skill_name):
                continue
            if rule.pattern.search(line):
                violations.append(Violation(path=path, line_no=line_no, line=line, rule=rule))

    return violations


def scan_paths(paths: list[Path]) -> list[Violation]:
    """Scan many files and return aggregated violations."""
    violations: list[Violation] = []
    for path in paths:
        violations.extend(scan_file(path))
    return violations


_TARGET_SUFFIXES = frozenset({".md", ".yaml", ".yml"})
_TARGET_NAMES = frozenset({"SKILL.md", "instructions.md", "playbook.yaml"})


def find_target_files(root: Path) -> list[Path]:
    """Return doc files under ``skills/`` that the scanner targets.

    Only files that ship instructions to agents — ``SKILL.md``, ``instructions.md``,
    and any ``.md``/``.yaml`` under a skill's ``references/`` directory — are
    in scope. Implementation files under ``scripts/`` are intentionally
    excluded; they ARE the wrapper.
    """
    if not root.is_dir():
        return []

    results: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix not in _TARGET_SUFFIXES:
            continue
        # Skip eval criteria files — they describe what to test, not what to do.
        if path.parent.name == "evals":
            continue
        # Skip script directories.
        if "scripts" in path.parts:
            continue
        if path.name in _TARGET_NAMES or "references" in path.parts:
            results.append(path)
    return results
