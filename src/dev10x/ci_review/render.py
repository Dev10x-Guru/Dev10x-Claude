from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path

from dev10x.ci_review.process import run_checked
from dev10x.core.domain.common.result import ErrorResult, Result, err, ok

INLINE_TOOL_PREFIX: str = "mcp__github_inline_comment__"

_HEREDOC = re.compile(r"^(\w+)<<(\S+)\n(.*?)\n\2$", re.MULTILINE | re.DOTALL)
_SINGLE_LINE = re.compile(r"^(\w+)=(.*)$", re.MULTILINE)


@dataclass(frozen=True)
class RenderedInputs:
    prompt: str
    claude_args: list[str]

    @property
    def uses_inline_comments(self) -> bool:
        return any(INLINE_TOOL_PREFIX in arg for arg in self.claude_args)


def run_context(*, repo: str, pr: int) -> str:
    return f"- REPO: {repo}\n- PR: {pr}\n"


def parse_github_output(*, raw: str) -> dict[str, str]:
    heredocs = {match.group(1): match.group(3) for match in _HEREDOC.finditer(raw)}
    single = dict(_SINGLE_LINE.findall(_HEREDOC.sub("", raw)))
    return {**single, **heredocs}


def render_inputs(
    *,
    scripts: Path,
    checkout: Path,
    build_inputs: tuple[str, ...],
    repo: str,
    pr: int,
    output: Path,
) -> Result[RenderedInputs]:
    output.write_text("", encoding="utf-8")
    built = run_checked(
        args=[str(scripts / "build-claude-inputs.sh"), *build_inputs],
        cwd=checkout,
        env={
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "CLAUDE_CI_DIR": str(checkout / ".github" / "claude"),
            "RUN_CONTEXT": run_context(repo=repo, pr=pr),
            "GITHUB_OUTPUT": str(output),
        },
        timeout=60,
    )
    if isinstance(built, ErrorResult):
        return built
    outputs = parse_github_output(raw=output.read_text(encoding="utf-8"))
    if "prompt" not in outputs or "claude_args" not in outputs:
        return err(f"build-claude-inputs.sh wrote no prompt/claude_args to {output}")
    return ok(
        RenderedInputs(
            prompt=outputs["prompt"],
            claude_args=shlex.split(outputs["claude_args"]),
        )
    )
