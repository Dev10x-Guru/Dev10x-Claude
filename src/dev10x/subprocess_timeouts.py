"""Detect unbounded subprocess calls in PEP 723 uv-scripts (GH-1414).

In-package code routes subprocess work through
`dev10x.subprocess_utils`, which bounds every call. A PEP 723
standalone script runs in a fresh isolated interpreter that cannot
import `dev10x` at all, so `.claude/rules/mcp-tools.md` asks each one to
declare a local `_SUBPROCESS_TIMEOUT_SECONDS` and pass `timeout=`
itself. That convention had no enforcement: two scripts followed it and
six did not, and three of the six run inside foreman's unattended night
loop where a hung `gh` or a keyring daemon waiting on a passphrase with
no TTY has no escalation path — the step stalls until morning instead of
failing visibly.

This module is the single detector shared by the pytest suite
(`tests/test_subprocess_timeouts.py`) and the pre-commit entry point
(`bin/check-subprocess-timeouts.py`), so the two never drift. It mirrors
`dev10x.dependency_pins`, the guard built for the same class of drift.

Scope, and why it is drawn here:

* **Only PEP 723 scripts are scanned.** A file without a `# /// script`
  header is in-package code, where `subprocess_utils` is the rule and a
  separate guard enforces it. Scanning both would double-report.
* **Only `run` / `check_output` / `check_call` are flagged.**
  `subprocess.Popen` takes no `timeout` in its constructor — the bound
  belongs on the later `.communicate(timeout=…)` / `.wait(timeout=…)` —
  so flagging a `Popen(...)` call for a missing `timeout=` would be a
  false positive, and a guard that cries wolf gets suppressed.
* **Detection is AST-based, not textual.** A regex over source cannot
  tell a call from a docstring that describes one, and this module's own
  prose is full of the latter.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

_logger = logging.getLogger(__name__)

SCANNED_SUFFIXES = frozenset({".py"})
# Mirrors dependency_pins.SKIPPED_DIRS: each worktree is a full checkout
# of this same repo, so scanning them re-reports every finding once per
# tree and lets a leftover tree fail the lint suite repo-wide.
SKIPPED_DIRS = frozenset(
    {".git", ".venv", "node_modules", "__pycache__", "dist", "build", "worktrees"}
)

PEP723_MARKER = "# /// script"

# The three subprocess entry points that accept a `timeout=` keyword.
TIMEOUT_AWARE_CALLS = frozenset({"run", "check_output", "check_call"})


def _has_pep723_header(text: str) -> bool:
    return any(line.startswith(PEP723_MARKER) for line in text.splitlines())


def is_pep723_script(*, path: Path) -> bool:
    """True when the file carries a PEP 723 inline-metadata header."""
    try:
        text = path.read_text()
    except (OSError, UnicodeDecodeError):
        _logger.warning("Skipping unreadable file during subprocess-timeout scan: %s", path)
        return False
    return _has_pep723_header(text)


def _call_name(node: ast.Call) -> str | None:
    """Return `subprocess.<name>` calls as `<name>`, everything else as None.

    Only the attribute form is recognised. A bare `run(...)` imported via
    `from subprocess import run` would be indistinguishable from any
    other local helper called `run`, and this repo's scripts all use the
    qualified form.
    """
    func = node.func
    if not isinstance(func, ast.Attribute):
        return None
    if not isinstance(func.value, ast.Name) or func.value.id != "subprocess":
        return None
    return func.attr


def _has_timeout(node: ast.Call) -> bool:
    """True when the call passes `timeout=`, or forwards unknown kwargs.

    A `**kwargs` splat could carry a timeout the AST cannot see, so it
    counts as bounded rather than producing a finding no reader can act
    on.
    """
    passes_timeout = any(keyword.arg == "timeout" for keyword in node.keywords)
    # `arg is None` is how ast spells `**kwargs` in a call's keyword list.
    forwards_unknown_kwargs = any(keyword.arg is None for keyword in node.keywords)
    return passes_timeout or forwards_unknown_kwargs


def find_unbounded_calls(*, path: Path, root: Path) -> list[str]:
    """Return `path:lineno: subprocess.<call>(...)` offenders in one script.

    Reads the file once and derives both the header check and the AST
    from that text. Calling `is_pep723_script` here instead would read
    every matched script twice — ~14% of this scan's runtime, paid on
    every commit via the pre-commit hook.
    """
    try:
        text = path.read_text()
    except (OSError, UnicodeDecodeError):
        _logger.warning("Skipping unreadable file during subprocess-timeout scan: %s", path)
        return []
    if not _has_pep723_header(text):
        return []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        _logger.warning("Skipping unparseable file during subprocess-timeout scan: %s", path)
        return []

    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name not in TIMEOUT_AWARE_CALLS:
            continue
        if _has_timeout(node):
            continue
        offenders.append(f"{path.relative_to(root)}:{node.lineno}: subprocess.{name}(...)")
    return offenders


def scanned_files(root: Path) -> list[Path]:
    # Excludes symlinks for the reason dependency_pins.scanned_files
    # documents: Path.rglob() follows symlinked directories on this
    # project's floor Python (3.12), so an unguarded scan could read a
    # symlink's target or hang on a cycle.
    return sorted(
        path
        for path in root.rglob("*")
        if path.suffix in SCANNED_SUFFIXES
        and path.is_file()
        and not path.is_symlink()
        and not SKIPPED_DIRS.intersection(path.relative_to(root).parts)
    )


def scan_repository(root: Path) -> list[str]:
    """Scan the whole tree and return every unbounded subprocess call."""
    offenders: list[str] = []
    for path in scanned_files(root):
        offenders.extend(find_unbounded_calls(path=path, root=root))
    return offenders
