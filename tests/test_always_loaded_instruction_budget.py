"""Guard the instruction text Claude Code loads into every session (GH-1606).

Claude Code loads every `.claude/rules/*.md` without `paths:` front matter,
plus `CLAUDE.md`, into every session in this repo, and warns once the total
passes 150k characters. Per-file line budgets never bounded that total, so it
crept past the limit release by release with no personal files at all.
"""

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).parents[1]
_RULES_DIR = _REPO_ROOT / ".claude" / "rules"

# Headroom below Claude Code's 150k warning, left for the user's own files.
ALWAYS_LOADED_BUDGET_CHARS = 140_000

_FRONT_MATTER = re.compile(r"\A---\n(?P<body>.*?)\n---\n", re.DOTALL)
_CONDITIONAL_ROW = re.compile(r"^\| `\.claude/rules/(?P<name>[\w-]+\.md)` \| When ", re.MULTILINE)


def has_paths_front_matter(text: str) -> bool:
    match = _FRONT_MATTER.match(text)
    return bool(match) and re.search(r"^paths:", match.group("body"), re.MULTILINE) is not None


def always_loaded_files() -> list[Path]:
    rules = [
        path
        for path in sorted(_RULES_DIR.glob("*.md"))
        if not has_paths_front_matter(text=path.read_text(encoding="utf-8"))
    ]
    return [_REPO_ROOT / "CLAUDE.md", *rules]


def conditional_rule_names() -> list[str]:
    index = (_RULES_DIR / "INDEX.md").read_text(encoding="utf-8")
    return _CONDITIONAL_ROW.findall(index)


@pytest.fixture
def always_loaded_sizes() -> dict[str, int]:
    return {
        str(path.relative_to(_REPO_ROOT)): len(path.read_text(encoding="utf-8"))
        for path in always_loaded_files()
    }


def test_always_loaded_instructions_fit_the_budget(always_loaded_sizes: dict[str, int]) -> None:
    total = sum(always_loaded_sizes.values())
    largest = sorted(always_loaded_sizes.items(), key=lambda item: item[1], reverse=True)[:3]

    assert total <= ALWAYS_LOADED_BUDGET_CHARS, (
        f"Always-loaded instructions total {total:,} chars, over the "
        f"{ALWAYS_LOADED_BUDGET_CHARS:,} budget (Claude Code warns at 150k). "
        f"Largest: {largest}. Add `paths:` front matter to a rule that only "
        "matters for some files, or move reference bulk to `references/`."
    )


def test_index_lists_conditional_rules() -> None:
    assert len(conditional_rule_names()) >= 10


@pytest.mark.parametrize("rule_name", conditional_rule_names())
def test_conditional_rule_carries_paths_front_matter(rule_name: str) -> None:
    text = (_RULES_DIR / rule_name).read_text(encoding="utf-8")

    assert has_paths_front_matter(text=text), (
        f"INDEX.md § Loading Strategy calls `{rule_name}` conditional, but it has "
        "no `paths:` front matter, so Claude Code loads it in every session."
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('---\npaths:\n  - "skills/**"\n---\n\n# Rule\n', True),
        ("# Rule\n\npaths: are mentioned in prose\n", False),
        ("---\ntitle: x\n---\n\n# Rule\n", False),
    ],
)
def test_has_paths_front_matter(text: str, expected: bool) -> None:
    assert has_paths_front_matter(text=text) is expected
