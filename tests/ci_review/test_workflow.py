from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.ci_review.workflow import (
    REVIEW_WORKFLOWS,
    ReviewJob,
    load_review_job,
    would_trigger,
)
from dev10x.core.domain.common.result import ErrorResult, SuccessResult

_WORKFLOWS: Path = Path(__file__).parents[2] / ".github" / "workflows"


def _load(*, name: str) -> ReviewJob:
    result = load_review_job(workflow_text=(_WORKFLOWS / name).read_text(encoding="utf-8"))
    assert isinstance(result, SuccessResult), result
    return result.value


class TestRealWorkflows:
    @pytest.fixture
    def code_review(self) -> ReviewJob:
        return _load(name=REVIEW_WORKFLOWS["code-review"])

    @pytest.fixture
    def hygiene(self) -> ReviewJob:
        return _load(name=REVIEW_WORKFLOWS["hygiene"])

    def test_code_review_job(self, code_review: ReviewJob) -> None:
        assert code_review.job_id == "claude-review"
        assert code_review.build_inputs == (
            "args/code-review.txt",
            "prompts/code-review.core.md",
            "prompts/code-review.output-ci.md",
        )
        assert code_review.guards == ("draft", "fork")
        assert code_review.keep_pr_head is True

    def test_hygiene_job(self, hygiene: ReviewJob) -> None:
        assert hygiene.job_id == "hygiene-review"
        assert hygiene.build_inputs == ("args/hygiene.txt", "prompts/hygiene.md")
        assert hygiene.guards == ("draft", "fork")
        assert hygiene.keep_pr_head is False

    def test_action_ref_is_the_pinned_sha(self, code_review: ReviewJob) -> None:
        assert len(code_review.action_ref) == 40

    def test_code_review_reads_the_paths_filter(self, code_review: ReviewJob) -> None:
        assert (code_review.paths[0], code_review.paths[-1], code_review.paths_ignore) == (
            "**/*.py",
            "!.github/workflows/claude*.yml",
            (),
        )

    def test_hygiene_has_no_paths_filter(self, hygiene: ReviewJob) -> None:
        assert (hygiene.paths, hygiene.paths_ignore) == ((), ())

    @pytest.mark.parametrize(
        ("files", "expected"),
        [
            (["src/a.py"], True),
            (["setup.py"], True),
            (["README.md", "docs/x.md"], False),
            (["skills/x/SKILL.md"], True),
            ([".github/workflows/claude-code-review.yml"], False),
            ([".github/workflows/ci.yml"], True),
            ([], False),
        ],
        ids=["nested-py", "root-py", "docs-only", "skill", "negated", "other-yml", "no-files"],
    )
    def test_real_code_review_filter(
        self, code_review: ReviewJob, files: list[str], expected: bool
    ) -> None:
        assert (
            would_trigger(
                files=files, paths=code_review.paths, paths_ignore=code_review.paths_ignore
            )
            is expected
        )


@pytest.mark.parametrize(
    ("files", "paths", "paths_ignore", "expected"),
    [
        (["a.md"], (), (), True),
        (["docs/a.md"], (), ("docs/**",), False),
        (["docs/a.md", "src/b.py"], (), ("docs/**",), True),
        (["docs/keep.md"], (), ("docs/**", "!docs/keep.md"), True),
        (["a/b.txt"], ("a/?.txt",), (), True),
        (["a/bc.txt"], ("a/?.txt",), (), False),
        (["a/b/c.txt"], ("a/*.txt",), (), False),
        (["a/b/c.txt"], ("a/**",), (), True),
        (["a+b.txt"], ("a+b.txt",), (), True),
        (["src/a.py"], ("src/[ab].py",), (), True),
        (["src/c.py"], ("src/[ab].py",), (), False),
        (["src/c.py"], ("src/[!ab].py",), (), True),
        (["src/a.py"], ("src/[!ab].py",), (), False),
        (["src/x/y.py"], ("src/x[!ab]y.py",), (), False),
        (["src/^.py"], ("src/[^].py",), (), True),
        (["src/[.py"], ("src/[.py",), (), True),
    ],
    ids=[
        "no-filter",
        "all-ignored",
        "one-not-ignored",
        "ignore-negated",
        "question-mark",
        "question-mark-one-char",
        "star-stays-in-dir",
        "double-star-crosses-dirs",
        "literal-escaped",
        "class-matches-member",
        "class-rejects-non-member",
        "negated-class-matches-non-member",
        "negated-class-rejects-member",
        "negated-class-stays-in-dir",
        "caret-is-a-member",
        "unclosed-bracket-is-literal",
    ],
)
def test_would_trigger(
    files: list[str],
    paths: tuple[str, ...],
    paths_ignore: tuple[str, ...],
    expected: bool,
) -> None:
    assert would_trigger(files=files, paths=paths, paths_ignore=paths_ignore) is expected


@pytest.mark.parametrize(
    "trigger",
    ["on: pull_request\n", "on: {pull_request: null}\n", ""],
    ids=["bare-event", "no-config", "no-on"],
)
def test_unfiltered_triggers_read_as_no_paths(trigger: str) -> None:
    text = (
        f"{trigger}jobs:\n  a:\n    steps:\n      - id: inputs\n"
        f"        run: ./build-claude-inputs.sh args/x.txt p.md\n{_ACTION_STEP}"
    )

    result = load_review_job(workflow_text=text)

    assert isinstance(result, SuccessResult)
    assert (result.value.paths, result.value.paths_ignore) == ((), ())


def test_reads_paths_ignore() -> None:
    text = (
        "on:\n  pull_request:\n    paths-ignore: ['docs/**']\n"
        "jobs:\n  a:\n    steps:\n      - id: inputs\n"
        f"        run: ./build-claude-inputs.sh args/x.txt p.md\n{_ACTION_STEP}"
    )

    result = load_review_job(workflow_text=text)

    assert isinstance(result, SuccessResult)
    assert result.value.paths_ignore == ("docs/**",)


_ACTION_STEP = "      - uses: anthropics/claude-code-action@abc\n"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("jobs: {a: [", "not valid YAML"),
        ("jobs:\n  a:\n    steps:\n      - run: echo\n", "no job running"),
        ("", "no job running"),
        (f"jobs:\n  a:\n    steps:\n{_ACTION_STEP}", "no `inputs` step"),
        (
            f"jobs:\n  a:\n    steps:\n      - id: inputs\n        run: echo hi\n{_ACTION_STEP}",
            "does not run build-claude-inputs.sh",
        ),
        (
            "jobs:\n  a:\n    steps:\n      - id: inputs\n"
            f"        run: ./build-claude-inputs.sh\n{_ACTION_STEP}",
            "does not run build-claude-inputs.sh",
        ),
    ],
    ids=["bad-yaml", "no-action", "empty", "no-inputs", "no-script", "no-args"],
)
def test_refuses_workflows_missing_steps(text: str, message: str) -> None:
    result = load_review_job(workflow_text=text)

    assert isinstance(result, ErrorResult)
    assert message in result.error


def test_minimal_job_without_guards_or_stage() -> None:
    text = (
        "jobs:\n  a:\n    steps:\n      - id: inputs\n"
        f"        run: ./build-claude-inputs.sh args/x.txt p.md\n{_ACTION_STEP}"
    )

    result = load_review_job(workflow_text=text)

    assert result == SuccessResult(
        value=ReviewJob(
            job_id="a",
            build_inputs=("args/x.txt", "p.md"),
            action_ref="abc",
            guards=(),
            keep_pr_head=False,
        )
    )
