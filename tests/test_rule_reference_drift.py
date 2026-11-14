"""Catch drift between rule files and the text that points at them (GH-1906).

Three kinds of drift went unnoticed until a review round happened to read
the right line:

- a `.claude/rules/*.md` or `references/*.md` path quoted in `src/`,
  `skills/`, `hooks/` or `references/` that no longer exists — validator
  messages and doctor remediations embed these as string literals;
- an INDEX.md Loading Strategy row that restates a rule's `paths:` globs
  by hand and no longer agrees with the front matter;
- a `paths:` glob that matches no tracked file, so a rename silently stops
  the rule from loading.
"""

from __future__ import annotations

import re
import subprocess
from functools import cache
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).parents[1]
_RULES_DIR = _REPO_ROOT / ".claude" / "rules"
_SCANNED_DIRS: tuple[str, ...] = ("src", "skills", "hooks", "references")
_SCANNED_SUFFIXES: frozenset[str] = frozenset({".py", ".md", ".yaml", ".yml", ".sh", ".json"})

_FRONT_MATTER = re.compile(r"\A---\n(?P<body>.*?)\n---\n", re.DOTALL)
_QUOTED_PATH = re.compile(
    r"(?P<prefix>[\w./<>{}*$-]*?)"
    r"(?P<path>(?:\.claude/rules|references)/[\w./-]+?\.md)"
    r"(?![\w/-])"
)
_PLACEHOLDER_CHARS = frozenset("<>{}*$")
_LOADING_ROW = re.compile(
    r"^\| `\.claude/rules/(?P<name>[\w-]+\.md)` \| When (?P<scope>[^|]*) \|",
    re.MULTILINE,
)
_BACKTICKED = re.compile(r"`(?P<token>[^`\s]+)`")

#: Quoted paths that are not references into this repo. Each entry names
#: the citing file and the exact quoted path, so a new stale reference in
#: the same file still fails.
_FOREIGN_REFERENCES: frozenset[tuple[str, str]] = frozenset(
    {
        # A file the skill generates in the user's repository.
        ("skills/gh-review-setup/instructions.md", "references/rules/review-guidelines.md"),
        # Eval fixtures that describe a hypothetical skill tree.
        ("skills/git-groom/evals/evals.json", "references/a.md"),
        ("skills/git-groom/evals/evals.json", "references/sub/a.md"),
        # The destination named by a split plan, not yet created.
        ("skills/plugin-maintenance/SKILL.md", "references/preflight.md"),
        # Generic per-skill file names in a migration how-to.
        ("references/orchestration/subagent-status-operations.md", "references/phases.md"),
        (
            "references/orchestration/subagent-status-operations.md",
            "references/example-plays.md",
        ),
    }
)

#: `paths:` globs that are deliberately broader than today's tree.
_SPECULATIVE_GLOBS: frozenset[tuple[str, str]] = frozenset(
    {
        # The alternate workflow extension; no workflow uses it yet.
        ("github-workflows.md", ".github/workflows/**/*.yaml"),
    }
)

#: Conditional rules known to lack an INDEX.md § Loading Strategy row. The
#: fix is an INDEX.md edit tracked by the issue named on each entry.
_MISSING_INDEX_ROWS: frozenset[str] = frozenset()


@cache
def tracked_files() -> tuple[str, ...]:
    completed = subprocess.run(
        ["git", "ls-files"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return tuple(completed.stdout.splitlines())


def expand_braces(pattern: str) -> list[str]:
    match = re.search(r"\{(?P<options>[^{}]*)\}", pattern)
    if match is None:
        return [pattern]
    head, tail = pattern[: match.start()], pattern[match.end() :]
    return [
        expanded
        for option in match.group("options").split(",")
        for expanded in expand_braces(pattern=f"{head}{option}{tail}")
    ]


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    parts: list[str] = []
    index = 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            parts.append("(?:.*/)?")
            index += 3
        elif pattern.startswith("**", index):
            parts.append(".*")
            index += 2
        elif pattern[index] == "*":
            parts.append("[^/]*")
            index += 1
        elif pattern[index] == "?":
            parts.append("[^/]")
            index += 1
        else:
            parts.append(re.escape(pattern[index]))
            index += 1
    return re.compile("".join(parts) + r"\Z")


def matching_files(pattern: str) -> set[str]:
    regexes = [glob_to_regex(pattern=expanded) for expanded in expand_braces(pattern=pattern)]
    return {path for path in tracked_files() if any(regex.match(path) for regex in regexes)}


def front_matter_paths(rule: Path) -> list[str]:
    match = _FRONT_MATTER.match(rule.read_text(encoding="utf-8"))
    if match is None:
        return []
    return list(yaml.safe_load(match.group("body")).get("paths") or [])


def rules_with_paths() -> list[Path]:
    return [rule for rule in sorted(_RULES_DIR.glob("*.md")) if front_matter_paths(rule=rule)]


def index_scope_globs() -> dict[str, list[str]]:
    index = (_RULES_DIR / "INDEX.md").read_text(encoding="utf-8")
    return {
        match.group("name"): [
            token.group("token")
            for token in _BACKTICKED.finditer(match.group("scope"))
            if "/" in token.group("token") or "." in token.group("token")
        ]
        for match in _LOADING_ROW.finditer(index)
    }


def scanned_files() -> list[Path]:
    return [
        path
        for directory in _SCANNED_DIRS
        for path in sorted((_REPO_ROOT / directory).rglob("*"))
        if path.suffix in _SCANNED_SUFFIXES and path.is_file()
    ]


def reference_resolves(citing: Path, prefix: str, path: str) -> bool:
    candidates = [
        _REPO_ROOT / path,
        _REPO_ROOT / f"{prefix}{path}",
        citing.parent / f"{prefix}{path}",
        *(ancestor / path for ancestor in citing.parents if ancestor.is_relative_to(_REPO_ROOT)),
    ]
    # A skill often names a sibling skill's reference by its short
    # `references/<file>.md` form, so any skill's copy satisfies it.
    sibling_skills = (_REPO_ROOT / "skills").glob(f"*/{path}")
    return any(candidate.is_file() for candidate in [*candidates, *sibling_skills])


def stale_references() -> list[str]:
    stale = []
    for citing in scanned_files():
        relative = str(citing.relative_to(_REPO_ROOT))
        for match in _QUOTED_PATH.finditer(citing.read_text(encoding="utf-8")):
            prefix, path = match.group("prefix"), match.group("path")
            if _PLACEHOLDER_CHARS.intersection(prefix + path):
                continue
            if (relative, path) in _FOREIGN_REFERENCES:
                continue
            if not reference_resolves(citing=citing, prefix=prefix, path=path):
                stale.append(f"{relative}: {path}")
    return stale


class TestQuotedRulePathsExist:
    def test_scan_reaches_the_validator_messages(self) -> None:
        scanned = {str(path.relative_to(_REPO_ROOT)) for path in scanned_files()}

        assert "src/dev10x/core/validators/spec_drift.py" in scanned

    def test_detector_flags_the_rule_gh1867_split_away(self) -> None:
        citing = _REPO_ROOT / "src" / "dev10x" / "core" / "validators" / "spec_drift.py"

        resolves = reference_resolves(
            citing=citing, prefix="", path=".claude/rules/hook-patterns.md"
        )

        assert resolves is False

    def test_every_quoted_rule_or_reference_path_exists(self) -> None:
        stale = stale_references()

        assert not stale, (
            "these quoted rule/reference paths point at files that do not exist "
            f"(rename the reference or restore the file): {stale}"
        )

    @pytest.mark.parametrize(("citing", "path"), sorted(_FOREIGN_REFERENCES))
    def test_foreign_reference_is_still_quoted(self, citing: str, path: str) -> None:
        assert path in (_REPO_ROOT / citing).read_text(encoding="utf-8"), (
            f"`{citing}` no longer quotes `{path}` — drop the allowlist entry"
        )


class TestIndexAgreesWithFrontMatter:
    def test_index_rows_are_parsed(self) -> None:
        assert len(index_scope_globs()) >= 10

    @pytest.mark.parametrize(
        ("rule_name", "glob"),
        [(name, glob) for name, globs in index_scope_globs().items() for glob in globs],
    )
    def test_index_glob_is_covered_by_front_matter(self, rule_name: str, glob: str) -> None:
        loaded = set().union(
            *(
                matching_files(pattern=path)
                for path in front_matter_paths(rule=_RULES_DIR / rule_name)
            )
        )

        uncovered = sorted(matching_files(pattern=glob) - loaded)

        assert not uncovered, (
            f"INDEX.md says `{rule_name}` loads for `{glob}`, but its `paths:` front "
            f"matter does not cover: {uncovered[:5]}"
        )

    @pytest.mark.parametrize(
        "rule",
        [
            pytest.param(
                rule,
                id=rule.name,
                marks=[pytest.mark.xfail(strict=True, reason="INDEX.md row owed")]
                * (rule.name in _MISSING_INDEX_ROWS),
            )
            for rule in rules_with_paths()
        ],
    )
    def test_conditional_rule_has_an_index_row(self, rule: Path) -> None:
        assert rule.name in index_scope_globs(), (
            f"`{rule.name}` has `paths:` front matter but no INDEX.md § Loading "
            "Strategy row, so readers of the index cannot tell when it loads."
        )


class TestPathsGlobsMatchTrackedFiles:
    @pytest.mark.parametrize(
        ("rule_name", "glob"),
        [
            (rule.name, glob)
            for rule in rules_with_paths()
            for glob in front_matter_paths(rule=rule)
            if (rule.name, glob) not in _SPECULATIVE_GLOBS
        ],
    )
    def test_paths_glob_matches_a_tracked_file(self, rule_name: str, glob: str) -> None:
        assert matching_files(pattern=glob), (
            f"`{rule_name}` front matter glob `{glob}` matches no tracked file, so the "
            "rule never loads for it — a rename probably left it behind."
        )

    @pytest.mark.parametrize(("rule_name", "glob"), sorted(_SPECULATIVE_GLOBS))
    def test_speculative_glob_is_still_declared(self, rule_name: str, glob: str) -> None:
        assert glob in front_matter_paths(rule=_RULES_DIR / rule_name)


@pytest.mark.parametrize(
    ("pattern", "path", "expected"),
    [
        ("skills/**", "skills/a/SKILL.md", True),
        ("hooks/**/*.py", "hooks/x.py", True),
        ("hooks/**/*.py", "hooks/scripts/x.sh", False),
        ("src/dev10x/*/hooks/**", "src/dev10x/core/hooks/a.py", True),
        ("src/dev10x/*/hooks/**", "src/dev10x/a/b/hooks/c.py", False),
        (".github/workflows/claude*.yml", ".github/workflows/claude-review.yml", True),
    ],
)
def test_glob_to_regex(pattern: str, path: str, expected: bool) -> None:
    assert bool(glob_to_regex(pattern=pattern).match(path)) is expected


def test_expand_braces() -> None:
    assert expand_braces(pattern="src/**/{skills,mcp}/**") == ["src/**/skills/**", "src/**/mcp/**"]
