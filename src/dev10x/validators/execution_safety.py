"""Validator: execution safety patterns.

Consolidates validate-bash-security.py (Bash branch) and
block-python3-inline.py.

Blocks:
  1. Shell-based file writes (cat >, echo >, printf >)
  2. In-place file editors (sed -i, perl -i, gawk -i inplace, dd of=)
  3. Interpreter inline code (python3 -c, bash/sh/zsh -c)
  4. Interpreters running untrusted absolute script paths
     (python3/bash/sh/zsh <untrusted-abs-path>)

The interpreter guard (GH-469) treats bash/sh/zsh as siblings of
python3: the `bash <verb> *` catch-all is the higher-severity footgun
(arbitrary shell, total rule bypass), so it must be hook-enforced here
rather than left to an unreliable permission deny-rule.
"""

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from dev10x.domain import HookInput, HookResult
from dev10x.domain.claude_paths import ClaudeDir
from dev10x.domain.profile_tier import ProfileTier
from dev10x.validators.base import ValidatorBase

SHELL_WRITE_RE = re.compile(
    r"\bcat\b\s*(>|<<|>\s*\S)"
    r"|\becho\b\s+.*\s*(>|>>)\s*\S"
    r"|\bprintf\b.*\s*(>|>>)\s*\S"
    r"|\$\(printf\b"
)

ENV_VAR_RE = re.compile(r"^[A-Z_][A-Z0-9_]*=\S*$")

# Matches dd of= writes to real files; excludes /dev/null, /dev/stdout, /dev/stderr
_DD_OF_RE = re.compile(r"\bof=(?!/dev/(null|stdout|stderr)\b)\S")

APPROVED_ABS_PREFIXES = (
    f"{ClaudeDir.tools_dir()}/",
    f"{ClaudeDir.skills_dir()}/",
    f"{ClaudeDir.hooks_dir()}/",
)

SHELL_WRITE_MSG = (
    "Use the Write/Edit tool instead of cat/echo/printf redirects.\n"
    "For multi-line commit messages: create a unique file with"
    " /tmp/Dev10x/bin/mktmp.sh git commit-msg .txt,"
    " Write content to the returned path, then git commit -F <path>"
)

INPLACE_EDIT_MSG = (
    "Use the Write/Edit tool instead of in-place stream editors"
    " (sed -i, perl -i, gawk -i inplace, dd of=).\n"
    "Read-only forms are fine: sed -n, sed/awk writing to stdout,"
    " perl -ne/-pe without -i."
)

PYTHON3_INLINE_MSG = """\
\U0001f6ab  python3 inline/untrusted script blocked.

Use the Write tool to create a self-contained uv script instead:

  Step 1 \u2014 Write the script to /tmp/Dev10x/<name>.py via the Write tool:

    #!/usr/bin/env -S uv run --script
    # /// script
    # requires-python = ">=3.11"
    # dependencies = []  # add packages here if needed, e.g. ["requests"]
    # ///

    # your code here

  Step 2 \u2014 Run it:

    uv run --script /tmp/Dev10x/<name>.py

Benefits:
  - Reproducible: deps declared inline (PEP 723), no pip install needed
  - Auditable: Write tool diffs show exactly what runs
  - Permitted: uv run:* is pre-approved; /tmp/Dev10x/ is writable

If the script needs no third-party deps, the # /// block can be omitted."""

SHELL_INTERPRETERS = ("bash", "sh", "zsh")

# Shell interpreters may additionally run scripts staged under the Dev10x
# temp dir (GH-370 pre-approves /tmp/Dev10x/ execution); python3 keeps the
# narrower APPROVED_ABS_PREFIXES set.
SHELL_APPROVED_ABS_PREFIXES = (*APPROVED_ABS_PREFIXES, "/tmp/Dev10x/")

SHELL_INTERP_MSG = """\
\U0001f6ab  shell inline/untrusted script execution blocked.

`bash`/`sh`/`zsh` running inline code (`-c`) or an untrusted absolute
script path bypasses every PreToolUse guardrail. Use one of:

  - Inline logic — Write a self-contained uv script to
    /tmp/Dev10x/<name>.py via the Write tool, then `uv run --script` it
    (auditable diff, declared deps, no rule bypass).
  - An existing script — run it directly via its shebang
    (./script.sh) instead of `bash script.sh`.
  - A staged script — place it under an approved dir and run it
    there: ~/.claude/{tools,skills,hooks}/ or /tmp/Dev10x/.

Relative paths (e.g. `bash ./build.sh`) and approved-dir absolute paths
are allowed; only inline `-c` and untrusted absolute paths are blocked."""


def _strip_env_prefix(parts: list[str]) -> list[str]:
    i = 0
    while i < len(parts) and ENV_VAR_RE.match(parts[i]):
        i += 1
    return parts[i:]


def _is_approved_path(path: str, prefixes: tuple[str, ...] = APPROVED_ABS_PREFIXES) -> bool:
    expanded = os.path.expanduser(path)
    return any(expanded.startswith(p) or path.startswith(p) for p in prefixes)


def _has_inplace_flag(*, argv: list[str], cmd: str) -> bool:
    """Return True if the argument list indicates an in-place edit operation.

    Handles:
    - sed: any short-flag cluster that contains 'i' (e.g. -i, -ni, -in, -in.bak)
    - perl: any short-flag cluster that contains 'i' (e.g. -i, -pi, -pi.bak)
    - gawk/awk: '-i' followed by 'inplace' as a separate token
    - dd: delegated to caller via _DD_OF_RE
    """
    if cmd in ("sed", "perl"):
        for arg in argv:
            # Only inspect short-flag clusters (start with '-' but not '--')
            if arg.startswith("-") and not arg.startswith("--"):
                # Strip the leading '-' and any optional suffix after the flags
                # e.g. '-i.bak' \u2192 flag letters = 'i', suffix = '.bak'
                # e.g. '-ni' \u2192 flag letters = 'ni'
                flag_body = arg[1:]
                # Collect contiguous alpha chars as the flag cluster
                flag_letters = ""
                for ch in flag_body:
                    if ch.isalpha():
                        flag_letters += ch
                    else:
                        break
                if "i" in flag_letters:
                    return True
        return False

    if cmd in ("gawk", "awk"):
        # gawk -i inplace: '-i' must be immediately followed by 'inplace'
        for idx, arg in enumerate(argv):
            if arg in ("-i", "--include") and idx + 1 < len(argv):
                if argv[idx + 1] == "inplace":
                    return True
        return False

    return False


@dataclass
class ExecutionSafetyValidator(ValidatorBase):
    name: ClassVar[str] = "execution-safety"
    rule_id: ClassVar[str] = "DX003"
    profile: ClassVar[ProfileTier] = ProfileTier.MINIMAL

    def should_run(self, inp: HookInput) -> bool:
        return True

    def validate(self, inp: HookInput) -> HookResult | None:
        # Check shell writes first; if flagged, report immediately.
        result = self._check_shell_writes(command=inp.command)
        if result:
            return result
        # Check in-place editors before python3 so mis-keyed sed/perl is caught
        # early, consistent with first-block-wins ordering.
        result = self._check_inplace_edit(command=inp.command)
        if result:
            return result
        return self._check_interpreter(command=inp.command)

    def _check_shell_writes(self, *, command: str) -> HookResult | None:
        if SHELL_WRITE_RE.search(command):
            return HookResult(message=SHELL_WRITE_MSG)
        return None

    def _check_inplace_edit(self, *, command: str) -> HookResult | None:
        """Detect in-place file editors and steer to Write/Edit tool.

        Scans each pipeline segment so `cat x | sed -i ...` is caught.
        Returns a HookResult on the first flagged segment, None otherwise.
        """
        _INPLACE_CMDS = frozenset({"sed", "perl", "gawk", "awk", "dd"})

        for segment in command.split("|"):
            segment = segment.strip()
            try:
                parts = shlex.split(segment)
            except ValueError:
                return None

            parts = _strip_env_prefix(parts)
            if not parts:
                continue

            cmd = parts[0]
            if cmd not in _INPLACE_CMDS:
                continue

            argv = parts[1:]

            if cmd == "dd":
                if _DD_OF_RE.search(segment):
                    return HookResult(message=INPLACE_EDIT_MSG)
                continue

            if _has_inplace_flag(argv=argv, cmd=cmd):
                return HookResult(message=INPLACE_EDIT_MSG)

        return None

    def _check_interpreter(self, *, command: str) -> HookResult | None:
        """Block inline code and untrusted absolute script paths for
        python3 and the shell interpreters (bash/sh/zsh).

        python3 keeps its `-m` carve-out and the narrow approved-prefix
        set; the shell interpreters additionally allow /tmp/Dev10x/.
        First match wins (python3 checked before the shells).
        """
        result = self._check_one_interpreter(
            command=command,
            interpreter="python3",
            approved=APPROVED_ABS_PREFIXES,
            message=PYTHON3_INLINE_MSG,
            allow_module=True,
        )
        if result:
            return result

        for interpreter in SHELL_INTERPRETERS:
            result = self._check_one_interpreter(
                command=command,
                interpreter=interpreter,
                approved=SHELL_APPROVED_ABS_PREFIXES,
                message=SHELL_INTERP_MSG,
                allow_module=False,
            )
            if result:
                return result

        return None

    def _check_one_interpreter(
        self,
        *,
        command: str,
        interpreter: str,
        approved: tuple[str, ...],
        message: str,
        allow_module: bool,
    ) -> HookResult | None:
        if interpreter not in command:
            return None

        first_cmd = command.split("|")[0].strip()

        try:
            parts = shlex.split(first_cmd)
        except ValueError:
            return None

        parts = _strip_env_prefix(parts)

        if not parts or parts[0] != interpreter:
            return None

        argv = parts[1:]

        if allow_module and "-m" in argv:
            return None

        if any(a == "-c" or a.startswith("-c") for a in argv):
            return HookResult(message=message)

        script = next(
            (a for a in argv if not a.startswith("-")),
            None,
        )

        if script is None or not Path(script).expanduser().is_absolute():
            return None

        if _is_approved_path(script, approved):
            return None

        return HookResult(message=message)
