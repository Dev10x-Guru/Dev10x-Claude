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


class TestAllowsTypecheckScripts:
    """GH-1025: `lint:tsc` runs only `tsc` — there is no inline linter to redirect."""

    @pytest.mark.parametrize(
        "command",
        [
            "yarn workspace @tt/shared lint:tsc",
            "yarn lint:tsc",
            "pnpm lint:types",
            "npm run lint:typecheck",
        ],
    )
    def test_allows(self, validator: InlineLinterValidator, command: str) -> None:
        assert validator.validate(inp=_make_input(command=command)) is None

    def test_still_blocks_a_sibling_lint_script(self, validator: InlineLinterValidator) -> None:
        # The exemption is script-name-scoped, not a blanket `lint:*` escape.
        result = validator.validate(
            inp=_make_input(command="yarn workspace @tt/shared lint:eslint")
        )
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


class TestAllowsSearchPatterns:
    """GH-1133: a linter name inside a quoted *argument* is not an invocation.

    The command is segmented with a quote-aware tokenizer, so a `|` inside a
    search pattern no longer manufactures a bare-linter segment.
    """

    @pytest.mark.parametrize(
        "command",
        [
            'rg -n "pre-commit|ruff|mypy" ~/.claude/settings.json',
            'rg "ruff" pyproject.toml',
            "git log --grep ruff",
            'rg -n "black|prettier" .',
            "grep -r 'eslint|prettier' src/",
        ],
    )
    def test_allows(self, validator: InlineLinterValidator, command: str) -> None:
        assert validator.validate(inp=_make_input(command=command)) is None

    @pytest.mark.parametrize(
        "command",
        [
            "python src/tools/mypy_plugin.py",
            "cat src/tools/ruff_helpers.py",
        ],
    )
    def test_allows_paths_containing_a_linter_name(
        self, validator: InlineLinterValidator, command: str
    ) -> None:
        assert validator.validate(inp=_make_input(command=command)) is None

    def test_still_blocks_a_real_invocation_after_a_quoted_pipe(
        self, validator: InlineLinterValidator
    ) -> None:
        # The quoted pipe must not swallow a genuine downstream invocation.
        result = validator.validate(inp=_make_input(command='rg -n "a|b" . | ruff check -'))
        assert result is not None


class TestSegmentsOnEveryCommandSeparator:
    """A separator the old raw `|` split missed still yields an invocation."""

    @pytest.mark.parametrize(
        "command",
        [
            "cd src && ruff check .",
            "echo hi; mypy src",
            "make build || black --check .",
        ],
    )
    def test_blocks(self, validator: InlineLinterValidator, command: str) -> None:
        result = validator.validate(inp=_make_input(command=command))
        assert result is not None
        assert result.message == INLINE_LINTER_MSG


class TestSeesPastShellKeywords:
    """Segmenting on `;` puts a keyword first — the linter must still show.

    Without keyword stripping the loop body reads as a `do` invocation,
    turning the GH-1133 false-positive fix into a false negative.
    """

    @pytest.mark.parametrize(
        "command",
        [
            "for f in *.py; do ruff check $f; done",
            "if true; then mypy src; fi",
            "{ ruff check .; }",
            "time ruff format src",
            "command eslint .",
        ],
    )
    def test_blocks(self, validator: InlineLinterValidator, command: str) -> None:
        result = validator.validate(inp=_make_input(command=command))
        assert result is not None
        assert result.message == INLINE_LINTER_MSG


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
