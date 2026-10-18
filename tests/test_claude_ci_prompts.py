"""Pin how the Claude CI reviews get their prompt and claude_args (GH-1625).

The code-review and hygiene prompts live in ``.github/claude/prompts/`` and
their ``claude_args`` in ``.github/claude/args/``, so the workflow, the
``gh-review-setup`` templates and a local review mode can read one text
instead of drifting copies. Three properties keep that worth having:

- the files hold no ``${{ }}``, or every run would write the prompt cache
  again instead of reading it (GH-1585);
- the workflows take both inputs from the build step, never inline;
- every Claude step leads with the same four flags, so the system prompt
  is one cached prefix across jobs.

The build script is exercised directly, as the workflow runs it.
"""

from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

_REPO_ROOT = Path(__file__).parents[1]
_CLAUDE_DIR = _REPO_ROOT / ".github" / "claude"
_WORKFLOWS = _REPO_ROOT / ".github" / "workflows"
_BUILD_SCRIPT = _REPO_ROOT / ".github" / "scripts" / "claude-pr-context" / "build-claude-inputs.sh"

_SHARED_PREFIX = [
    "--settings",
    ".github/claude-ci-settings.json",
    "--append-system-prompt-file",
    ".github/claude/ci-system-prompt.md",
    "--exclude-dynamic-system-prompt-sections",
    "--disallowed-tools",
    "ScheduleWakeup,Monitor",
]

#: Workflows whose prompt and claude_args come from .github/claude/ files.
_FILE_DRIVEN_WORKFLOWS = ("claude-code-review.yml", "claude-pr-hygiene.yml")

#: Workflows still carrying inline claude_args (out of GH-1625's scope).
_INLINE_ARGS_WORKFLOWS = ("claude.yml", "claude-memory-review.yml")

_ACTION = "anthropics/claude-code-action"


def _claude_steps(*, workflow: str) -> list[dict[str, Any]]:
    document = yaml.safe_load((_WORKFLOWS / workflow).read_text(encoding="utf-8"))
    return [
        step
        for job in document["jobs"].values()
        for step in job["steps"]
        if step.get("uses", "").startswith(_ACTION)
    ]


def _build(*, tmp_path: Path, claude_dir: Path, args_file: str, parts: list[str]) -> str:
    output = tmp_path / "github_output"
    output.write_text("", encoding="utf-8")
    subprocess.run(
        [str(_BUILD_SCRIPT), args_file, *parts],
        cwd=_REPO_ROOT,
        env={
            "PATH": "/usr/bin:/bin",
            "CLAUDE_CI_DIR": str(claude_dir),
            "GITHUB_OUTPUT": str(output),
            "RUN_CONTEXT": "- REPO: owner/repo\n- PR: 42\n",
        },
        capture_output=True,
        check=True,
        timeout=30,
    )
    return output.read_text(encoding="utf-8")


def _parse_outputs(*, raw: str) -> dict[str, str]:
    outputs: dict[str, str] = {}
    lines = iter(raw.splitlines())
    for line in lines:
        name, _, value = line.partition("=")
        heredoc = re.fullmatch(r"(\w+)<<(\S+)", line)
        multiline = heredoc is not None
        outputs.update(
            {heredoc.group(1): "\n".join(_until(lines=lines, delimiter=heredoc.group(2)))}
            if multiline
            else {name: value}
        )
    return outputs


def _until(*, lines: Any, delimiter: str) -> list[str]:
    collected: list[str] = []
    for line in lines:
        if line == delimiter:
            return collected
        collected.append(line)
    raise AssertionError(f"heredoc delimiter {delimiter} never closed")


@pytest.mark.parametrize(
    "path",
    sorted((_CLAUDE_DIR / "prompts").glob("*.md")) + sorted((_CLAUDE_DIR / "args").glob("*.txt")),
    ids=lambda path: path.name,
)
def test_prompt_and_args_files_hold_no_expressions(path: Path) -> None:
    assert "${{" not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "path", sorted((_CLAUDE_DIR / "args").glob("*.txt")), ids=lambda p: p.name
)
def test_args_files_are_one_line(path: Path) -> None:
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


@pytest.mark.parametrize(
    "path", sorted((_CLAUDE_DIR / "args").glob("*.txt")), ids=lambda p: p.name
)
def test_args_files_lead_with_the_shared_prefix(path: Path) -> None:
    tokens = shlex.split(path.read_text(encoding="utf-8"))

    assert tokens[: len(_SHARED_PREFIX)] == _SHARED_PREFIX


@pytest.mark.parametrize("workflow", _INLINE_ARGS_WORKFLOWS)
def test_inline_claude_args_lead_with_the_shared_prefix(workflow: str) -> None:
    prefixes = [
        shlex.split(step["with"]["claude_args"])[: len(_SHARED_PREFIX)]
        for step in _claude_steps(workflow=workflow)
    ]

    assert prefixes == [_SHARED_PREFIX] * len(prefixes)


@pytest.mark.parametrize("workflow", _FILE_DRIVEN_WORKFLOWS)
def test_file_driven_steps_take_inputs_from_the_build_step(workflow: str) -> None:
    inputs = [
        (step["with"]["prompt"], step["with"]["claude_args"])
        for step in _claude_steps(workflow=workflow)
    ]

    assert inputs == [
        ("${{ steps.inputs.outputs.prompt }}", "${{ steps.inputs.outputs.claude_args }}")
    ]


@pytest.mark.parametrize("workflow", _FILE_DRIVEN_WORKFLOWS)
def test_build_step_names_files_that_exist(workflow: str) -> None:
    document = yaml.safe_load((_WORKFLOWS / workflow).read_text(encoding="utf-8"))
    (build,) = [
        step
        for job in document["jobs"].values()
        for step in job["steps"]
        if step.get("id") == "inputs"
    ]
    named = shlex.split(build["run"])[1:]

    assert [(_CLAUDE_DIR / name).is_file() for name in named] == [True] * len(named)


class TestBuildScript:
    @pytest.fixture
    def outputs(self, tmp_path: Path) -> dict[str, str]:
        raw = _build(
            tmp_path=tmp_path,
            claude_dir=_CLAUDE_DIR,
            args_file="args/code-review.txt",
            parts=["prompts/code-review.core.md", "prompts/code-review.output-ci.md"],
        )
        return _parse_outputs(raw=raw)

    def test_claude_args_is_the_args_file(self, outputs: dict[str, str]) -> None:
        expected = (_CLAUDE_DIR / "args" / "code-review.txt").read_text(encoding="utf-8")

        assert outputs["claude_args"] == expected.rstrip("\n")

    def test_prompt_starts_with_the_static_core(self, outputs: dict[str, str]) -> None:
        core = (_CLAUDE_DIR / "prompts" / "code-review.core.md").read_text(encoding="utf-8")

        assert outputs["prompt"].startswith(core.rstrip("\n") + "\n\n")

    def test_prompt_ends_with_run_context(self, outputs: dict[str, str]) -> None:
        assert outputs["prompt"].endswith("RUN CONTEXT:\n- REPO: owner/repo\n- PR: 42\n")

    def test_refuses_a_part_holding_an_expression(self, tmp_path: Path) -> None:
        claude_dir = tmp_path / "claude"
        (claude_dir / "args").mkdir(parents=True)
        (claude_dir / "args" / "job.txt").write_text("--model haiku\n", encoding="utf-8")
        (claude_dir / "part.md").write_text("PR: ${{ github.ref }}\n", encoding="utf-8")

        with pytest.raises(subprocess.CalledProcessError):
            _build(
                tmp_path=tmp_path,
                claude_dir=claude_dir,
                args_file="args/job.txt",
                parts=["part.md"],
            )


class TestRoutingParity:
    """The CI review routes by INDEX.md alone (GH-1619).

    A hand-copied agent list in the prompt drifted from INDEX.md and left
    the security and silent-failure reviewers out of every CI review.
    """

    _INDEX = _REPO_ROOT / ".claude" / "rules" / "INDEX.md"
    _CORE = _CLAUDE_DIR / "prompts" / "code-review.core.md"

    @pytest.fixture(scope="class")
    def routes(self) -> dict[str, list[str]]:
        text = self._INDEX.read_text(encoding="utf-8")
        table = text.split("## File Patterns -> Agents", 1)[1].split("\n## ", 1)[0]
        rows = [line for line in table.splitlines() if line.startswith("| `")]
        return {
            pattern: re.findall(r"`([^`]+)`", row.split("|")[2])
            for row in rows
            for pattern in re.findall(r"`([^`]+)`", row.split("|")[1])
        }

    def test_core_prompt_routes_by_index(self) -> None:
        core = self._CORE.read_text(encoding="utf-8")

        assert ".claude/rules/INDEX.md" in core
        assert "→ reviewer-" not in core

    def test_every_routed_agent_has_a_spec(self, routes: dict[str, list[str]]) -> None:
        agents = sorted({agent for names in routes.values() for agent in names})
        specs = [
            (_REPO_ROOT / ".claude" / "agents" / f"{agent}.md").is_file()
            or (_REPO_ROOT / "agents" / f"{agent}.md").is_file()
            for agent in agents
        ]

        assert dict(zip(agents, specs)) == dict.fromkeys(agents, True)

    def test_every_internal_reviewer_is_reachable(self, routes: dict[str, list[str]]) -> None:
        routed = {agent for names in routes.values() for agent in names}
        internal = {
            path.stem for path in (_REPO_ROOT / ".claude" / "agents").glob("reviewer-*.md")
        }

        assert internal - routed == set()

    def test_python_reaches_security_and_silent_failure_reviewers(
        self, routes: dict[str, list[str]]
    ) -> None:
        assert {"reviewer-security", "reviewer-silent-failures"} <= set(routes["**/*.py"])

    @pytest.mark.parametrize(
        "pattern",
        [".github/workflows/**", "references/**", "CLAUDE.md"],
    )
    def test_index_covers_paths_the_old_inline_list_routed(
        self, routes: dict[str, list[str]], pattern: str
    ) -> None:
        assert routes[pattern]
