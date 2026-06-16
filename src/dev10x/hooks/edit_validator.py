"""Edit/Write tool validator — blocks sensitive file writes and spec drift.

Two validation passes:

1. YAML-rule pass: loads rules from command-skill-map.yaml where
   matcher="Edit|Write", delegates evaluation to RuleEngine.
   First block wins.

2. Python-validator pass: runs active Edit|Write validators from the
   shared ValidatorRegistry (e.g. SpecDriftValidator / DX015).
   Only validators whose ``should_run()`` returns True participate.
"""

from __future__ import annotations

import functools
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dev10x.domain.events.hook_input import HookInput, HookResult
from dev10x.hooks.hook_transport import emit

if TYPE_CHECKING:
    from dev10x.domain.rules.rule_engine import RuleEngine

_YAML_PATH = Path(__file__).parent.parent / "validators" / "command-skill-map.yaml"


@functools.cache
def _cached_engine(yaml_path_str: str, mtime_ns: int) -> RuleEngine:
    """Build a RuleEngine for one (path, mtime) pair.

    GH-586: ``_build_engine`` previously re-parsed the YAML config on
    every ``Edit``/``Write`` hook invocation. Keying the cache on the
    file's mtime parses an unchanged config once per process while an
    edit to the YAML (new mtime) transparently yields a fresh engine.
    Mirrors the ``_cached_registry`` pattern in
    ``dev10x.validators.__init__``.
    """
    from dev10x.config.loader import load_config
    from dev10x.domain.rules.rule_engine import RuleEngine

    config = load_config(yaml_path=Path(yaml_path_str))
    return RuleEngine.from_config(config=config)


def _build_engine(*, yaml_path: Path) -> RuleEngine:
    try:
        mtime_ns = yaml_path.stat().st_mtime_ns
    except OSError:
        # Missing/unreadable config: bypass the cache with a sentinel
        # mtime and let load_config surface the error as before.
        mtime_ns = -1
    return _cached_engine(str(yaml_path), mtime_ns)


def reset_engine_cache() -> None:
    """Clear cached RuleEngine instances — used by tests."""
    _cached_engine.cache_clear()


def _run_python_validators(*, data: dict[str, Any], debug: bool = False) -> None:
    """Run Python validators that handle Edit|Write tool calls.

    Mirrors the dispatch pattern in ``commands/hook.py:_validate_bash_body``
    but filters to validators whose ``should_run`` returns True for the
    given Edit|Write input.  YAML-rule blocks have already been handled
    before this function is called.
    """
    from dev10x.validators import get_chain

    inp = HookInput.from_dict(data=data)
    for result in get_chain().run(inp=inp):
        if debug:
            import sys as _sys

            print(
                f"[DEBUG] Python validator blocked: {result}",
                file=_sys.stderr,
            )
        emit(result)


def validate_edit_write(
    *,
    data: dict[str, Any],
    yaml_path: Path | None = None,
    debug: bool = False,
) -> None:
    tool = data.get("tool_name", "")
    if tool not in ("Edit", "Write"):
        sys.exit(0)

    inp = data.get("tool_input", {})
    file_path = inp.get("file_path", "")
    content = inp.get("new_string") or inp.get("content", "")

    resolved_path = yaml_path or _YAML_PATH
    engine = _build_engine(yaml_path=resolved_path)

    if debug:
        print(f"[DEBUG] Loaded {len(engine.edit_rules)} Edit|Write rules", file=sys.stderr)

    match = engine.evaluate(file_path=file_path, content=content)
    if match:
        if debug:
            print(
                f"[DEBUG] Rule '{match.rule_name}' matched: {file_path}",
                file=sys.stderr,
            )
        emit(HookResult(message=match.message))

    _run_python_validators(data=data, debug=debug)

    sys.exit(0)
