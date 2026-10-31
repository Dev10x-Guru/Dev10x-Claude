from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from dev10x.ci_review import render
from dev10x.ci_review.render import RenderedInputs, parse_github_output, render_inputs
from dev10x.core.domain.common.result import ErrorResult, SuccessResult, ok

_REPO_ROOT: Path = Path(__file__).parents[2]
_SCRIPTS: Path = _REPO_ROOT / ".github" / "scripts" / "claude-pr-context"


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    root = tmp_path / "checkout"
    shutil.copytree(_REPO_ROOT / ".github" / "claude", root / ".github" / "claude")
    return root


class TestRealBuildScript:
    @pytest.fixture
    def rendered(self, tmp_path: Path, checkout: Path) -> RenderedInputs:
        result = render_inputs(
            scripts=_SCRIPTS,
            checkout=checkout,
            build_inputs=("args/hygiene.txt", "prompts/hygiene.md"),
            repo="owner/repo",
            pr=42,
            output=tmp_path / "inputs.out",
        )
        assert isinstance(result, SuccessResult), result
        return result.value

    def test_prompt_ends_with_run_context(self, rendered: RenderedInputs) -> None:
        assert rendered.prompt.endswith("RUN CONTEXT:\n- REPO: owner/repo\n- PR: 42\n")

    def test_prompt_starts_with_the_part(self, rendered: RenderedInputs) -> None:
        part = (_REPO_ROOT / ".github" / "claude" / "prompts" / "hygiene.md").read_text(
            encoding="utf-8"
        )

        assert rendered.prompt.startswith(part.rstrip("\n"))

    def test_args_are_split(self, rendered: RenderedInputs) -> None:
        assert rendered.claude_args[:2] == ["--settings", ".github/claude-ci-settings.json"]
        assert "ScheduleWakeup,Monitor" in rendered.claude_args

    def test_hygiene_has_no_inline_tool(self, rendered: RenderedInputs) -> None:
        assert rendered.uses_inline_comments is False


def test_code_review_uses_inline_tool(tmp_path: Path, checkout: Path) -> None:
    result = render_inputs(
        scripts=_SCRIPTS,
        checkout=checkout,
        build_inputs=("args/code-review.txt", "prompts/code-review.core.md"),
        repo="owner/repo",
        pr=1,
        output=tmp_path / "inputs.out",
    )

    assert isinstance(result, SuccessResult)
    assert result.value.uses_inline_comments is True


def test_missing_part_fails(tmp_path: Path, checkout: Path) -> None:
    result = render_inputs(
        scripts=_SCRIPTS,
        checkout=checkout,
        build_inputs=("args/hygiene.txt", "prompts/gone.md"),
        repo="owner/repo",
        pr=1,
        output=tmp_path / "inputs.out",
    )

    assert isinstance(result, ErrorResult)
    assert "is missing" in result.details["stderr"]


def test_empty_output_fails(
    tmp_path: Path, checkout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(render, "run_checked", lambda **_: ok(""))

    result = render_inputs(
        scripts=_SCRIPTS,
        checkout=checkout,
        build_inputs=("args/hygiene.txt",),
        repo="o/r",
        pr=1,
        output=tmp_path / "inputs.out",
    )

    assert isinstance(result, ErrorResult)
    assert "wrote no prompt" in result.error


def test_parse_github_output() -> None:
    raw = "claude_args=--model x\nprompt<<EOF_1\nline one\nline two\nEOF_1\n"

    assert parse_github_output(raw=raw) == {
        "claude_args": "--model x",
        "prompt": "line one\nline two",
    }
