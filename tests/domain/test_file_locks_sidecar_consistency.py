"""Guard the file_locks sidecar-naming footgun (GH-1442).

``file_lock`` / ``locked_yaml_update`` *append* ``.lock`` to the
target's full name (``plan.yaml`` -> ``plan.yaml.lock``);
``locked_json_update`` *replaces* the target's suffix
(``settings.local.json`` -> ``settings.local.lock``). Two writers of
the same path reaching for different helpers would take different
sidecars and fail to exclude each other, silently.

This is documented as a footgun, not a live bug: a sweep found no
path currently mixes the two conventions, and changing the scheme
would orphan on-disk sidecars across an upgrade boundary. The
insurance is this test — parse every call site of the three helpers
and assert no single path expression appears under both sidecar
families, so a future call site that would collide fails loudly here
instead of silently at runtime.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Family A appends ".lock" to the full name; family B replaces the suffix.
APPEND_SUFFIX_HELPERS = frozenset({"file_lock", "locked_yaml_update"})
REPLACE_SUFFIX_HELPERS = frozenset({"locked_json_update"})
ALL_HELPERS = APPEND_SUFFIX_HELPERS | REPLACE_SUFFIX_HELPERS

SKIPPED_DIRS = frozenset(
    {".git", ".venv", "node_modules", "__pycache__", "dist", "build", "worktrees"}
)


def _scanned_files() -> list[Path]:
    return sorted(
        path
        for path in (REPO_ROOT / "src").rglob("*.py")
        if path.is_file()
        and not path.is_symlink()
        and not SKIPPED_DIRS.intersection(path.relative_to(REPO_ROOT).parts)
    )


def _path_arg_key(call: ast.Call) -> str | None:
    """Return a stable text key for the call's path argument, or None."""
    arg: ast.expr | None = None
    for keyword in call.keywords:
        if keyword.arg == "path":
            arg = keyword.value
            break
    if arg is None and call.args:
        arg = call.args[0]
    if arg is None:
        return None
    try:
        return ast.dump(arg)
    except Exception:  # pragma: no cover - defensive, ast.dump rarely fails
        return None


def _collect_helper_calls() -> dict[str, set[str]]:
    """Map a defining module + path-expression key to the helper families used."""
    usage: dict[str, set[str]] = {}
    for source_file in _scanned_files():
        if source_file.name == "file_locks.py":
            continue  # the definitions themselves, not call sites
        try:
            tree = ast.parse(source_file.read_text(), filename=str(source_file))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else None
            if name not in ALL_HELPERS:
                continue
            key_part = _path_arg_key(node)
            if key_part is None:
                continue
            key = f"{source_file}:{key_part}"
            family = "append" if name in APPEND_SUFFIX_HELPERS else "replace"
            usage.setdefault(key, set()).add(family)
    return usage


def test_no_path_expression_mixes_sidecar_families() -> None:
    usage = _collect_helper_calls()
    offenders = {key: families for key, families in usage.items() if len(families) > 1}
    assert offenders == {}, (
        "A path expression is reached through both the append-suffix "
        "(file_lock/locked_yaml_update) and replace-suffix "
        "(locked_json_update) sidecar conventions — two writers of the "
        "same path would take different .lock files and fail to "
        "exclude each other:\n"
        f"{offenders}"
    )


def test_detector_sees_known_call_sites() -> None:
    """Sanity check the detector itself is not silently finding nothing."""
    usage = _collect_helper_calls()
    assert len(usage) > 5, (
        "Expected to find multiple file_lock/locked_json_update/"
        "locked_yaml_update call sites under src/ — the detector may be "
        "broken rather than the codebase being clean."
    )
