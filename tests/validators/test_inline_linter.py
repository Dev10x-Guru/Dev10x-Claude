"""Tests for InlineLinterValidator (DX016, GH-596)."""

from __future__ import annotations

import pytest

from dev10x.validators.inline_linter import INLINE_LINTER_MSG, InlineLinterValidator
from tests.fakers import BashHookInputFaker


def _make_input(*, command: str) -> BashHookInputFaker:
    return BashHookInputFaker.build(command=command)


@pytest.fixture()
def validator() -> InlineLinterValidator:
    return InlineLinterValidator()


class TestShouldRun:
    @pytest.mark.parametrize(
        "command",
        ["ruff check .", "uv run black src", "npx eslint .", "pnpm lint"],
    )
    def test_runs_for_linter_commands(
        self, validator: InlineLinterValidator, command: str
    ) -> None:
        assert validator.should_run(inp=_make_input(command=command)) is True

    @pytest.mark.parametrize(
        "command",
        ["git status", "uv run pytest", "pre-commit run --all-files"],
    )
    def test_skips_unrelated_commands(
        self, validator: InlineLinterValidator, command: str
    ) -> None:
        assert validator.should_run(inp=_make_input(command=command)) is False


class TestBlocksBareLinters:
    @pytest.mark.parametrize(
        "command",
        [
            "ruff check .",
            "ruff format src",
            "black --check .",
            "isort .",
            "mypy src",
            "eslint .",
            "prettier --write .",
        ],
    )
    def test_blocks(self, validator: InlineLinterValidator, command: str) -> None:
        result = validator.validate(inp=_make_input(command=command))
        assert result is not None
        assert result.message == INLINE_LINTER_MSG


class TestBlocksWrappedLinters:
    @pytest.mark.parametrize(
        "command",
        [
            "uv run ruff check .",
            "uv run --frozen ruff format .",
            "npx eslint .",
            "npx -y prettier --write .",
            "pnpm exec eslint .",
            "poetry run black .",
            "pipx run ruff check .",
            "python -m ruff check .",
            "python3 -m mypy src",
            "pnpm lint",
            "pnpm run lint",
            "yarn lint",
            "npm run lint:js",
        ],
    )
    def test_blocks(self, validator: InlineLinterValidator, command: str) -> None:
        result = validator.validate(inp=_make_input(command=command))
        assert result is not None
        assert result.message == INLINE_LINTER_MSG

    def test_blocks_linter_in_pipeline_segment(self, validator: InlineLinterValidator) -> None:
        result = validator.validate(inp=_make_input(command="git diff | ruff check -"))
        assert result is not None


class TestAllowsNonLinters:
    @pytest.mark.parametrize(
        "command",
        [
            "pre-commit run --files src/foo.py",
            "uv run pre-commit run",
            "uv run pytest tests/",
            "uv run python script.py",
            "python -m pytest",
            "yarn add eslint",  # installing, not running
            "pnpm run build",
            "git commit -m 'fix ruff config'",
            "cat ruff.toml",
        ],
    )
    def test_allows(self, validator: InlineLinterValidator, command: str) -> None:
        assert validator.validate(inp=_make_input(command=command)) is None


class TestEdgeCases:
    def test_env_prefix_stripped_before_match(self, validator: InlineLinterValidator) -> None:
        # An `ENV=val` prefix must be stripped so the linter is still caught.
        result = validator.validate(inp=_make_input(command="FORCE_COLOR=1 ruff check ."))
        assert result is not None

    def test_unbalanced_quote_is_ignored(self, validator: InlineLinterValidator) -> None:
        # shlex raises on an unterminated quote — the segment is skipped, not blocked.
        assert validator.validate(inp=_make_input(command="ruff check 'oops")) is None

    def test_empty_leading_segment_skipped(self, validator: InlineLinterValidator) -> None:
        # An empty pipeline segment is skipped; the real linter segment blocks.
        result = validator.validate(inp=_make_input(command="| ruff check ."))
        assert result is not None


class TestMetadata:
    def test_rule_id_and_profile(self, validator: InlineLinterValidator) -> None:
        from dev10x.domain.profile_tier import ProfileTier

        assert validator.rule_id == "DX016"
        assert validator.profile is ProfileTier.STANDARD
