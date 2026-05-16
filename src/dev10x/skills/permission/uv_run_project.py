"""GH-137: detect `uv run --project <path> <tool>` monorepo pattern.

`Bash(uv run pre-commit run:*)` does not match `uv run --project apps/api
pre-commit run ...` because the engine tokenizes `uv run --project` as the
prefix. This module:

1. Scans recorded Bash commands for `uv run <FLAGS> <tool>` shapes.
2. Extracts the `--project <path>` argument (the most common driver).
3. Proposes one `Bash(uv run --project <path>:*)` rule per detected
   pyproject directory — covering every subcommand uv launches into
   that project (pytest, ruff, mypy, pre-commit, etc).

Per @wooyek's review on GH-137: emit ONE rule per detected
pyproject.toml directory, not N rules per (project × tool) pair.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

UV_RUN_PROJECT_RE = re.compile(
    r"\buv\s+run\s+"
    r"(?:--(?:project|frozen|no-sync|extra|with)\s+\S+\s+)+"
    r"(?P<tool>\S+)"
)

PROJECT_FLAG_RE = re.compile(r"--project\s+(?P<path>\S+)")


@dataclass
class UvRunProjectMatch:
    command: str
    project_path: str
    tool: str


@dataclass
class UvRunProjectProposal:
    project_path: str
    rule: str
    tools_seen: list[str] = field(default_factory=list)


def detect(*, commands: list[str]) -> list[UvRunProjectMatch]:
    """Return matches for ``uv run --project <path> <tool>`` shapes."""
    matches: list[UvRunProjectMatch] = []
    for cmd in commands:
        uv_match = UV_RUN_PROJECT_RE.search(cmd)
        if not uv_match:
            continue
        project_match = PROJECT_FLAG_RE.search(cmd)
        if not project_match:
            continue
        matches.append(
            UvRunProjectMatch(
                command=cmd,
                project_path=project_match.group("path"),
                tool=uv_match.group("tool"),
            )
        )
    return matches


def propose_rules(*, matches: list[UvRunProjectMatch]) -> list[UvRunProjectProposal]:
    """Collapse matches into one allow-rule per project directory.

    Multiple tools invoked under the same `--project` share one rule:
    ``Bash(uv run --project <path>:*)`` covers every subcommand.
    """
    by_project: dict[str, list[str]] = {}
    for m in matches:
        by_project.setdefault(m.project_path, []).append(m.tool)

    proposals: list[UvRunProjectProposal] = []
    for project_path, tools in sorted(by_project.items()):
        unique_tools = sorted(set(tools))
        proposals.append(
            UvRunProjectProposal(
                project_path=project_path,
                rule=f"Bash(uv run --project {project_path}:*)",
                tools_seen=unique_tools,
            )
        )
    return proposals
