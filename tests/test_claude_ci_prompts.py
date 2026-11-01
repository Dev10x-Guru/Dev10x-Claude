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

import functools
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any, ClassVar

import pytest
import yaml

_REPO_ROOT: Path = Path(__file__).parents[1]
_CLAUDE_DIR: Path = _REPO_ROOT / ".github" / "claude"
_WORKFLOWS: Path = _REPO_ROOT / ".github" / "workflows"
_BUILD_SCRIPT: Path = (
    _REPO_ROOT / ".github" / "scripts" / "claude-pr-context" / "build-claude-inputs.sh"
)

_PROMPT_FILES: list[Path] = sorted((_CLAUDE_DIR / "prompts").glob("*.md"))
_ARGS_FILES: list[Path] = sorted((_CLAUDE_DIR / "args").glob("*.txt"))

#: Every file whose text lands in a cached prefix: prompts, args, and the
#: system prompt each job appends.
_PREFIX_FILES: list[Path] = [*_PROMPT_FILES, *_ARGS_FILES, _CLAUDE_DIR / "ci-system-prompt.md"]

_HEREDOC = re.compile(r"^(\w+)<<(\S+)\n(.*?)\n\2$", re.MULTILINE | re.DOTALL)
_SINGLE_LINE = re.compile(r"^(\w+)=(.*)$", re.MULTILINE)

_SHARED_PREFIX: list[str] = [
    "--settings",
    ".github/claude-ci-settings.json",
    "--append-system-prompt-file",
    ".github/claude/ci-system-prompt.md",
    "--exclude-dynamic-system-prompt-sections",
    "--disallowed-tools",
    "ScheduleWakeup,Monitor",
]

#: Workflows whose prompt and claude_args come from .github/claude/ files.
_FILE_DRIVEN_WORKFLOWS: tuple[str, ...] = ("claude-code-review.yml", "claude-pr-hygiene.yml")

#: Workflows still carrying inline claude_args (out of GH-1625's scope).
_INLINE_ARGS_WORKFLOWS: tuple[str, ...] = ("claude.yml", "claude-memory-review.yml")

_ACTION: str = "anthropics/claude-code-action"


@functools.cache
def _load_workflow(*, workflow: str) -> dict[str, Any]:
    return yaml.safe_load((_WORKFLOWS / workflow).read_text(encoding="utf-8"))


def _claude_steps(*, workflow: str) -> list[dict[str, Any]]:
    document = _load_workflow(workflow=workflow)
    return [
        step
        for job in document["jobs"].values()
        for step in job["steps"]
        if step.get("uses", "").startswith(_ACTION)
    ]


def _run_build(
    *, tmp_path: Path, claude_dir: Path, args_file: str, parts: list[str]
) -> subprocess.CompletedProcess[str]:
    output = tmp_path / "github_output"
    output.write_text("", encoding="utf-8")
    return subprocess.run(
        [str(_BUILD_SCRIPT), args_file, *parts],
        cwd=_REPO_ROOT,
        env={
            "PATH": "/usr/bin:/bin",
            "CLAUDE_CI_DIR": str(claude_dir),
            "GITHUB_OUTPUT": str(output),
            "RUN_CONTEXT": "- REPO: owner/repo\n- PR: 42\n",
        },
        capture_output=True,
        text=True,
        timeout=30,
    )


def _parse_outputs(*, raw: str) -> dict[str, str]:
    heredocs = {match.group(1): match.group(3) for match in _HEREDOC.finditer(raw)}
    single = dict(_SINGLE_LINE.findall(_HEREDOC.sub("", raw)))
    return {**single, **heredocs}


@pytest.mark.parametrize("files", [_PROMPT_FILES, _ARGS_FILES], ids=["prompts", "args"])
def test_every_glob_finds_files(files: list[Path]) -> None:
    assert files


@pytest.mark.parametrize("path", _PREFIX_FILES, ids=lambda path: path.name)
def test_prefix_files_hold_no_expressions(path: Path) -> None:
    assert "${{" not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", _ARGS_FILES, ids=lambda path: path.name)
def test_args_files_are_one_line(path: Path) -> None:
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


@pytest.mark.parametrize("path", _ARGS_FILES, ids=lambda path: path.name)
def test_args_files_lead_with_the_shared_prefix(path: Path) -> None:
    tokens = shlex.split(path.read_text(encoding="utf-8"))

    assert tokens[: len(_SHARED_PREFIX)] == _SHARED_PREFIX


@pytest.mark.parametrize("workflow", _INLINE_ARGS_WORKFLOWS)
def test_inline_claude_args_lead_with_the_shared_prefix(workflow: str) -> None:
    prefixes = [
        shlex.split(step["with"]["claude_args"])[: len(_SHARED_PREFIX)]
        for step in _claude_steps(workflow=workflow)
    ]

    assert len(prefixes) > 0
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
    missing = [name for name in named if not (_CLAUDE_DIR / name).is_file()]

    assert named
    assert missing == []


@pytest.mark.parametrize("workflow", _FILE_DRIVEN_WORKFLOWS)
def test_stage_step_uses_the_shared_staging_script(workflow: str) -> None:
    document = yaml.safe_load((_WORKFLOWS / workflow).read_text(encoding="utf-8"))
    (stage,) = [
        step
        for job in document["jobs"].values()
        for step in job["steps"]
        if step.get("id") == "stage"
    ]

    assert '"$RUNNER_TEMP/scripts/stage-trusted.sh" "$ref"' in stage["run"]


class TestBuildScript:
    @pytest.fixture
    def outputs(self, tmp_path: Path) -> dict[str, str]:
        result = _run_build(
            tmp_path=tmp_path,
            claude_dir=_CLAUDE_DIR,
            args_file="args/code-review.txt",
            parts=["prompts/code-review.core.md", "prompts/code-review.output-ci.md"],
        )
        assert result.returncode == 0, result.stderr
        return _parse_outputs(raw=(tmp_path / "github_output").read_text(encoding="utf-8"))

    @pytest.fixture
    def scratch_dir(self, tmp_path: Path) -> Path:
        claude_dir = tmp_path / "claude"
        (claude_dir / "args").mkdir(parents=True)
        (claude_dir / "args" / "job.txt").write_text("--model haiku\n", encoding="utf-8")
        (claude_dir / "part.md").write_text("Review the PR.\n", encoding="utf-8")
        return claude_dir

    def test_claude_args_is_the_args_file(self, outputs: dict[str, str]) -> None:
        expected = (_CLAUDE_DIR / "args" / "code-review.txt").read_text(encoding="utf-8")

        assert outputs["claude_args"] == expected.rstrip("\n")

    def test_prompt_starts_with_the_static_core(self, outputs: dict[str, str]) -> None:
        core = (_CLAUDE_DIR / "prompts" / "code-review.core.md").read_text(encoding="utf-8")

        assert outputs["prompt"].startswith(core.rstrip("\n") + "\n\n")

    def test_prompt_ends_with_run_context(self, outputs: dict[str, str]) -> None:
        assert outputs["prompt"].endswith("RUN CONTEXT:\n- REPO: owner/repo\n- PR: 42\n")

    @pytest.mark.parametrize(
        ("relative", "content", "message"),
        [
            ("part.md", "PR: ${{ github.ref }}\n", "contains ${{ }}"),
            ("args/job.txt", "--model haiku\n--tools Read", "exactly one line"),
            ("args/job.txt", "--model ${{ vars.MODEL }}\n", "contains ${{ }}"),
        ],
        ids=["expression-in-part", "two-line-args", "expression-in-args"],
    )
    def test_refuses_bad_input(
        self, tmp_path: Path, scratch_dir: Path, relative: str, content: str, message: str
    ) -> None:
        (scratch_dir / relative).write_text(content, encoding="utf-8")

        result = _run_build(
            tmp_path=tmp_path, claude_dir=scratch_dir, args_file="args/job.txt", parts=["part.md"]
        )

        assert result.returncode == 1
        assert message in result.stderr

    def test_refuses_a_missing_part(self, tmp_path: Path, scratch_dir: Path) -> None:
        result = _run_build(
            tmp_path=tmp_path, claude_dir=scratch_dir, args_file="args/job.txt", parts=["gone.md"]
        )

        assert result.returncode == 1
        assert "is missing" in result.stderr


class TestRoutingParity:
    """The CI review routes by INDEX.md alone (GH-1619).

    A hand-copied agent list in the prompt drifted from INDEX.md and left
    the security and silent-failure reviewers out of every CI review.
    """

    _INDEX: ClassVar[Path] = _REPO_ROOT / ".claude" / "rules" / "INDEX.md"
    _CORE: ClassVar[Path] = _CLAUDE_DIR / "prompts" / "code-review.core.md"
    _HEADING: ClassVar[str] = "## File Patterns -> Agents"

    @pytest.fixture(scope="class")
    def routes(self) -> dict[str, list[str]]:
        text = self._INDEX.read_text(encoding="utf-8")
        assert self._HEADING in text, f"INDEX.md lost its {self._HEADING!r} table"
        table = text.split(self._HEADING, 1)[1].split("\n## ", 1)[0]
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
        agents = {agent for names in routes.values() for agent in names}
        missing = {
            agent
            for agent in agents
            if not (_REPO_ROOT / ".claude" / "agents" / f"{agent}.md").is_file()
            and not (_REPO_ROOT / "agents" / f"{agent}.md").is_file()
        }

        assert missing == set()

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
        [".github/**", "references/**", "CLAUDE.md"],
    )
    def test_index_covers_paths_the_review_triggers_on(
        self, routes: dict[str, list[str]], pattern: str
    ) -> None:
        assert routes[pattern]


@functools.cache
def _normalized(*, path: Path) -> str:
    text = re.sub(r"^\s*>\s?", "", path.read_text(encoding="utf-8"), flags=re.MULTILINE)
    return " ".join(text.split())


_COVERAGE_FIRST: str = (
    "Report every issue you find, including ones you are uncertain about or "
    "consider low-severity. Do not filter for importance or confidence — the "
    "orchestrator verifies and ranks findings. For each finding include "
    "file:line, severity (CRITICAL / WARNING / INFO), confidence, and a "
    "one-sentence rationale."
)

#: The shared doc and the CI prompt state every shared rule.
_ROUTING_AND_CORE: list[str] = [
    "references/review-routing.md",
    ".github/claude/prompts/code-review.core.md",
]

#: Each shared rule, paired with every document that must state it.
_SHARED_RULES: list[tuple[str, str]] = [
    *[
        (document, _COVERAGE_FIRST)
        for document in [*_ROUTING_AND_CORE, "skills/review/references/domain-dispatch.md"]
    ],
    *[
        (document, rule)
        for rule in [
            "in ONE message so they run in parallel",
            "more than ~15 changed files",
            "File Patterns -> Agents",
            "the dropped count in the summary",
        ]
        for document in _ROUTING_AND_CORE
    ],
]


class TestSharedRouting:
    """CI and the local self-review route by one written rule set (GH-1741)."""

    _SKILL: ClassVar[Path] = _REPO_ROOT / "skills" / "review" / "SKILL.md"

    @pytest.mark.parametrize(("document", "rule"), _SHARED_RULES)
    def test_document_states_the_shared_rule(self, document: str, rule: str) -> None:
        assert rule in _normalized(path=_REPO_ROOT / document), f"{document} lost: {rule!r}"

    @pytest.mark.parametrize(
        "relative",
        [
            ".github/claude/prompts/code-review.core.md",
            "skills/review/SKILL.md",
            "skills/review/references/domain-dispatch.md",
        ],
    )
    def test_every_consumer_points_at_the_shared_doc(self, relative: str) -> None:
        text = (_REPO_ROOT / relative).read_text(encoding="utf-8")

        assert "references/review-routing.md" in text

    def test_local_review_keeps_no_agent_list_of_its_own(self) -> None:
        skill = self._SKILL.read_text(encoding="utf-8")

        assert "→ reviewer-" not in skill
        assert ".claude/rules/INDEX.md" in skill


class TestReviewVerdict:
    """The CI review submits the state its verdict names (GH-1693)."""

    _OUTPUT: ClassVar[Path] = _CLAUDE_DIR / "prompts" / "code-review.output-ci.md"
    _CORE: ClassVar[Path] = _CLAUDE_DIR / "prompts" / "code-review.core.md"

    @pytest.mark.parametrize(
        "command",
        [
            "--request-changes --body-file review-summary-body.md",
            "--approve --body-file review-summary-body.md",
        ],
    )
    def test_verdict_is_submitted_as_a_review_state(self, command: str) -> None:
        assert command in self._OUTPUT.read_text(encoding="utf-8")

    def test_comment_is_no_longer_the_default_state(self) -> None:
        output = self._OUTPUT.read_text(encoding="utf-8")

        assert "gh pr review <PR> --comment --body-file" not in output

    def test_revert_is_a_finding_not_a_bare_state(self) -> None:
        core = self._CORE.read_text(encoding="utf-8")

        assert "→ REQUEST_CHANGES" not in core

    def test_draft_step_also_drafts_on_requested_changes(self) -> None:
        document = yaml.safe_load(
            (_WORKFLOWS / "claude-code-review.yml").read_text(encoding="utf-8")
        )
        (step,) = [
            step
            for step in document["jobs"]["claude-review"]["steps"]
            if step["name"] == "Convert to draft when the review left findings"
        ]

        assert '.state == "CHANGES_REQUESTED"' in step["run"]

    def test_review_that_posted_nothing_fails(self) -> None:
        document = yaml.safe_load(
            (_WORKFLOWS / "claude-code-review.yml").read_text(encoding="utf-8")
        )
        (step,) = [
            step
            for step in document["jobs"]["claude-review"]["steps"]
            if step["name"] == "Fail if the review posted nothing"
        ]

        assert "steps.claude-review.outputs.conclusion == 'success'" in step["if"]
        assert step["env"]["SINCE"] == "${{ steps.review-start.outputs.iso }}"


class TestDraftConversion:
    """A shell step, not the model, drafts a PR with findings (GH-1618)."""

    @pytest.fixture(scope="class")
    def step_names(self) -> list[str]:
        document = yaml.safe_load(
            (_WORKFLOWS / "claude-code-review.yml").read_text(encoding="utf-8")
        )
        return [step["name"] for step in document["jobs"]["claude-review"]["steps"]]

    def test_model_is_not_given_gh_pr_ready(self) -> None:
        # Bash(gh api:*) can still reach the GraphQL draft mutations; the
        # prompt, not the allowlist, keeps the model off them.
        args = (_CLAUDE_DIR / "args" / "code-review.txt").read_text(encoding="utf-8")

        assert "gh pr ready" not in args

    def test_draft_step_runs_after_probe_cleanup(self, step_names: list[str]) -> None:
        assert step_names.index("Convert to draft when the review left findings") > (
            step_names.index("Delete probe inline comments")
        )


def _steps_by_name(*, workflow: str) -> dict[str, dict[str, Any]]:
    document = _load_workflow(workflow=workflow)
    return {step["name"]: step for job in document["jobs"].values() for step in job["steps"]}


#: Each file-driven review workflow and the id of its Claude step.
_REVIEW_STEP_IDS: list[tuple[str, str]] = [
    ("claude-code-review.yml", "claude-review"),
    ("claude-pr-hygiene.yml", "hygiene-review"),
]


class TestSilentReview:
    """A review that never ran must not pass green (GH-1691)."""

    _SKIP_GUARDS: ClassVar[tuple[str, ...]] = (
        "steps.dedup.outputs.skip != 'true'",
        "steps.pr-state.outputs.skip != 'true'",
        "steps.stage.outputs.skip != 'true'",
    )

    @pytest.mark.parametrize(("workflow", "step_id"), _REVIEW_STEP_IDS)
    def test_never_ran_guard_fails_on_a_missing_conclusion(
        self, workflow: str, step_id: str
    ) -> None:
        condition = _steps_by_name(workflow=workflow)["Fail if the review never ran"]["if"]

        assert f"steps.{step_id}.outputs.conclusion == ''" in condition

    @pytest.mark.parametrize("workflow", _FILE_DRIVEN_WORKFLOWS)
    @pytest.mark.parametrize("guard", _SKIP_GUARDS)
    def test_never_ran_guard_spares_a_deliberate_skip(self, workflow: str, guard: str) -> None:
        condition = _steps_by_name(workflow=workflow)["Fail if the review never ran"]["if"]

        assert guard in condition

    @pytest.mark.parametrize(("workflow", "step_id"), _REVIEW_STEP_IDS)
    def test_denial_report_runs_after_any_attempt(self, workflow: str, step_id: str) -> None:
        condition = _steps_by_name(workflow=workflow)["Report permission denials"]["if"]

        assert "always()" in condition
        assert f"steps.{step_id}.outputs.execution_file != ''" in condition


class TestReviewScope:
    """The review judges the diff, never the merge decision (GH-1691)."""

    def test_core_prompt_keeps_merge_state_out_of_findings(self) -> None:
        core = (_CLAUDE_DIR / "prompts" / "code-review.core.md").read_text(encoding="utf-8")

        assert "REVIEW THE DIFF, NOT THE MERGE DECISION" in core

    def test_injection_flag_never_becomes_an_inline_comment(self) -> None:
        output = (_CLAUDE_DIR / "prompts" / "code-review.output-ci.md").read_text(encoding="utf-8")

        assert "Never raise it as an inline comment" in output


class TestMentionDiffReads:
    """@claude reads one patch at a time, never the whole diff (GH-1691)."""

    @pytest.fixture(scope="class")
    def step(self) -> dict[str, Any]:
        (step,) = _claude_steps(workflow="claude.yml")
        return step

    def test_allowlist_has_no_whole_diff_command(self, step: dict[str, Any]) -> None:
        assert "Bash(gh pr diff:*)" not in step["with"]["claude_args"]

    def test_prompt_reads_patches_from_the_files_endpoint(self, step: dict[str, Any]) -> None:
        assert "gh api repos/<REPO>/pulls/<PR>/files --paginate" in step["with"]["prompt"]


def _trigger_types(*, workflow: str) -> list[str]:
    # PyYAML reads the bare `on:` key as the boolean True.
    return _load_workflow(workflow=workflow)[True]["pull_request"]["types"]


class TestReviewCadence:
    """The review runs once per ready flip; a push drafts the PR (GH-1694)."""

    def test_review_does_not_run_on_every_push(self) -> None:
        assert _trigger_types(workflow="claude-code-review.yml") == ["opened", "ready_for_review"]

    def test_a_push_drafts_the_pr(self) -> None:
        assert _trigger_types(workflow="pr-draft-on-push.yml") == ["synchronize"]

    def test_draft_on_push_skips_drafts_and_forks(self) -> None:
        condition = _load_workflow(workflow="pr-draft-on-push.yml")["jobs"]["draft"]["if"]

        assert "!github.event.pull_request.draft" in condition
        assert "head.repo.full_name == github.repository" in condition

    def test_draft_on_push_fails_loudly_without_app_credentials(self) -> None:
        steps = _steps_by_name(workflow="pr-draft-on-push.yml")
        guard = steps["Refuse to run without the App credentials"]["run"]

        assert "exit 1" in guard


class TestReviewChecklist:
    """Each review run stamps its id and sha into the PR body (GH-1694)."""

    _BEGIN: ClassVar[str] = "<!-- BEGIN claude-review-checklist -->"
    _END: ClassVar[str] = "<!-- END claude-review-checklist -->"

    @pytest.fixture(scope="class")
    def steps(self) -> dict[str, dict[str, Any]]:
        return _steps_by_name(workflow="claude-code-review.yml")

    @pytest.fixture(scope="class")
    def output(self) -> str:
        return (_CLAUDE_DIR / "prompts" / "code-review.output-ci.md").read_text(encoding="utf-8")

    @pytest.mark.parametrize("key", ["- RUN_ID: ", "- SHA: "])
    def test_run_context_carries_the_stamp(
        self, steps: dict[str, dict[str, Any]], key: str
    ) -> None:
        assert key in steps["Build Claude inputs"]["env"]["RUN_CONTEXT"]

    def test_guard_runs_after_a_successful_review(self, steps: dict[str, dict[str, Any]]) -> None:
        guard = steps["Fail if the review left no fresh checklist"]

        assert "steps.claude-review.outputs.conclusion == 'success'" in guard["if"]

    @pytest.mark.parametrize("needle", [_BEGIN, _END, "GITHUB_RUN_ID", "REVIEWED_SHA"])
    def test_guard_matches_the_stamped_block(
        self, steps: dict[str, dict[str, Any]], needle: str
    ) -> None:
        assert needle in steps["Fail if the review left no fresh checklist"]["run"]

    @pytest.mark.parametrize(
        "needle",
        [_BEGIN, _END, "STEP 7", "run <RUN_ID> · sha <SHA>", "review-checklist-body.md"],
    )
    def test_prompt_instructs_the_refresh(self, output: str, needle: str) -> None:
        assert needle in output

    def test_format_reference_documents_the_same_markers(self) -> None:
        reference = (_REPO_ROOT / "references" / "review-checklist-format.md").read_text(
            encoding="utf-8"
        )

        assert self._BEGIN in reference
        assert self._END in reference
