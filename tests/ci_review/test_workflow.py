from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.ci_review.workflow import REVIEW_WORKFLOWS, ReviewJob, load_review_job
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
