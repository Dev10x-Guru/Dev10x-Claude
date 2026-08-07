"""Guard the retired ``~/.claude/memory/Dev10x/`` tree in source (GH-1045).

GH-941 rehomed tier-2 user config to ``~/.config/Dev10x/``. The
``retired-durable-pref-path`` CLI-friction rule polices skill *docs*, but its
pattern keys on a ``Write(...)`` / ``Edit(...)`` tool call, which never appears
in Python or YAML source — so the one genuine code defect GH-1045 found
(``discovery.py`` resolving playbook overrides exclusively from the retired
tree, making every ``~/.config/Dev10x/playbooks`` override invisible) scanned
clean for four months.

This is the sibling check for source files. A mention of the retired tree is
allowed only where it is visibly a legacy read-compat fallback: the marker must
appear on the same line or in the two lines above it. That keeps the one-release
compat window documentable while failing a bare reference that reads as the
current location.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).parents[1]

#: Source trees the doc-only scanner does not reach.
_SCANNED_GLOBS: tuple[str, ...] = (
    "src/dev10x/**/*.py",
    "src/dev10x/**/*.yaml",
    "skills/**/*.py",
    "hooks/**/*.py",
    "bin/**/*.py",
)

_RETIRED_PATH = re.compile(r"\.claude/memory/Dev10x")

#: Words that mark a mention as a deliberate read-compat fallback rather than
#: an assertion about where config lives today.
_LEGACY_MARKER = re.compile(
    r"legacy|retired|fallback|formerly|deprecated|moved from|GH-941",
    re.IGNORECASE,
)

#: How many preceding lines may carry the marker for a mention (a comment block
#: above a constant is the common shape).
_MARKER_LOOKBEHIND = 2


def _unmarked_mentions(path: Path) -> list[tuple[int, str]]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    offending: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        if not _RETIRED_PATH.search(line):
            continue
        window = lines[max(0, index - _MARKER_LOOKBEHIND) : index + 1]
        if any(_LEGACY_MARKER.search(candidate) for candidate in window):
            continue
        offending.append((index + 1, line.strip()))
    return offending


def _scanned_files() -> list[Path]:
    return sorted({path for glob in _SCANNED_GLOBS for path in _REPO_ROOT.glob(glob)})


class TestRetiredMemoryPathInSource:
    def test_scan_covers_the_module_that_regressed(self) -> None:
        """Fail loud if the glob stops reaching the GH-1045 defect site."""
        discovery = _REPO_ROOT / "src" / "dev10x" / "skills" / "playbook" / "discovery.py"
        assert discovery in _scanned_files()

    def test_no_unmarked_retired_path_in_source(self) -> None:
        offenders = {
            str(path.relative_to(_REPO_ROOT)): mentions
            for path in _scanned_files()
            if (mentions := _unmarked_mentions(path))
        }
        assert offenders == {}, (
            "Source names the retired ~/.claude/memory/Dev10x/ tree without marking "
            "it as a legacy fallback. Point at ~/.config/Dev10x/ instead, or add a "
            "legacy/retired/fallback note on the line (or the two lines above it).\n"
            f"{offenders}"
        )


class TestMarkerDetection:
    """The guard's own logic — a scanner nobody trusts gets disabled."""

    def test_bare_mention_is_reported(self, tmp_path: Path) -> None:
        source = tmp_path / "sample.py"
        source.write_text('CONFIG = "~/.claude/memory/Dev10x/playbooks"\n')
        assert _unmarked_mentions(source) == [(1, 'CONFIG = "~/.claude/memory/Dev10x/playbooks"')]

    def test_marker_on_the_same_line_is_accepted(self, tmp_path: Path) -> None:
        source = tmp_path / "sample.py"
        source.write_text('LEGACY_DIR = "~/.claude/memory/Dev10x/playbooks"\n')
        assert _unmarked_mentions(source) == []

    def test_marker_in_a_comment_above_is_accepted(self, tmp_path: Path) -> None:
        source = tmp_path / "sample.py"
        source.write_text('# Read-compat fallback only.\nD = "~/.claude/memory/Dev10x/x"\n')
        assert _unmarked_mentions(source) == []

    def test_marker_too_far_above_is_not_accepted(self, tmp_path: Path) -> None:
        source = tmp_path / "sample.py"
        source.write_text('# legacy\n\n\n\nD = "~/.claude/memory/Dev10x/x"\n')
        assert len(_unmarked_mentions(source)) == 1
