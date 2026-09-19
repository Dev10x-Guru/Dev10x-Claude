"""Lint test: every uv-script subprocess call declares a timeout (GH-1414).

See `dev10x.subprocess_timeouts` for the rationale and the shared
detector used here and by `bin/check-subprocess-timeouts.py` (wired into
`.pre-commit-config.yaml`). Mirrors `tests/test_dependency_pins.py`, the
guard built for the same class of drift.
"""

from __future__ import annotations

from pathlib import Path

from dev10x.subprocess_timeouts import (
    find_unbounded_calls,
    is_pep723_script,
    scan_repository,
)
from dev10x.subprocess_utils import get_plugin_root

_PEP723_HEADER = "#!/usr/bin/env -S uv run --script\n# /// script\n# ///\n"


def _script(tmp_path: Path, body: str, *, name: str = "tool.py") -> Path:
    path = tmp_path / name
    path.write_text(_PEP723_HEADER + "import subprocess\n" + body)
    return path


def test_every_uv_script_subprocess_call_is_bounded() -> None:
    root = get_plugin_root()
    offenders = scan_repository(root)

    assert not offenders, (
        "A PEP 723 script cannot import dev10x.subprocess_utils, so an "
        "unbounded subprocess call hangs forever on a stalled `gh` or a "
        "keyring daemon with no TTY — in an unattended night run, until "
        "morning (GH-1414). Declare a local _SUBPROCESS_TIMEOUT_SECONDS "
        "and pass timeout=. Offenders:\n  - " + "\n  - ".join(offenders)
    )


def test_lint_detects_an_unbounded_run(tmp_path: Path) -> None:
    script = _script(tmp_path, 'subprocess.run(["gh", "pr", "list"])\n')

    assert find_unbounded_calls(path=script, root=tmp_path) == ["tool.py:5: subprocess.run(...)"]


def test_lint_accepts_a_bounded_run(tmp_path: Path) -> None:
    script = _script(tmp_path, 'subprocess.run(["gh"], timeout=30)\n')

    assert find_unbounded_calls(path=script, root=tmp_path) == []


def test_lint_flags_check_output_and_check_call(tmp_path: Path) -> None:
    script = _script(
        tmp_path,
        'subprocess.check_output(["gh"])\nsubprocess.check_call(["gh"])\n',
    )

    assert find_unbounded_calls(path=script, root=tmp_path) == [
        "tool.py:5: subprocess.check_output(...)",
        "tool.py:6: subprocess.check_call(...)",
    ]


def test_lint_ignores_popen_which_takes_no_constructor_timeout(tmp_path: Path) -> None:
    """Popen's bound belongs on communicate()/wait(), not the constructor.

    Flagging it here would be a false positive, and a guard that cries
    wolf gets suppressed.
    """
    script = _script(tmp_path, 'subprocess.Popen(["gh"])\n')

    assert find_unbounded_calls(path=script, root=tmp_path) == []


def test_lint_accepts_a_forwarded_kwargs_splat(tmp_path: Path) -> None:
    """A **kwargs splat may carry a timeout the AST cannot see."""
    script = _script(tmp_path, 'subprocess.run(["gh"], **kwargs)\n')

    assert find_unbounded_calls(path=script, root=tmp_path) == []


def test_lint_skips_a_file_with_no_pep723_header(tmp_path: Path) -> None:
    """In-package code is bound by subprocess_utils and its own guard."""
    module = tmp_path / "module.py"
    module.write_text('import subprocess\nsubprocess.run(["gh"])\n')

    assert find_unbounded_calls(path=module, root=tmp_path) == []


def test_lint_ignores_a_local_helper_named_run(tmp_path: Path) -> None:
    """Only the qualified `subprocess.run` form is recognised."""
    script = _script(tmp_path, 'run(["gh"])\n')

    assert find_unbounded_calls(path=script, root=tmp_path) == []


def test_lint_survives_an_unparseable_script(tmp_path: Path) -> None:
    script = tmp_path / "broken.py"
    script.write_text(_PEP723_HEADER + "def (\n")

    assert find_unbounded_calls(path=script, root=tmp_path) == []


def test_pep723_detection_reads_the_script_marker(tmp_path: Path) -> None:
    script = _script(tmp_path, "")
    plain = tmp_path / "plain.py"
    plain.write_text("import subprocess\n")

    assert is_pep723_script(path=script)
    assert not is_pep723_script(path=plain)
