"""Tests for WriteDestinationValidator (GH-1245)."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest

from dev10x.domain import HookResult
from dev10x.validators.write_destination import (
    WriteDestinationValidator,
    _destinations,
)
from tests.fakers import BashHookInputFaker

REPO = "/work/dx/repo"


def _make_input(*, command: str, cwd: str = REPO) -> BashHookInputFaker:
    return BashHookInputFaker.build(command=command, cwd=cwd)


@pytest.fixture()
def synthetic_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """Treat ``cwd`` as the checkout root without touching the filesystem.

    ``REPO`` does not exist, so the real walk-up would depend on whether
    some ancestor of it happens to be a checkout on the host running the
    suite. The parsing and containment rules under test are independent
    of how the root was found; ``TestWorkingTreeIsTheCheckoutNotTheCwd``
    exercises the real resolution.
    """
    monkeypatch.setattr(
        "dev10x.validators.write_destination._working_tree",
        lambda *, cwd: PurePosixPath(cwd),
    )


class TestBlocksWritesIntoTheWorkingTree:
    @pytest.fixture()
    def validator(self, synthetic_root: None) -> WriteDestinationValidator:
        return WriteDestinationValidator()

    @pytest.mark.parametrize(
        "command",
        [
            # The GH-1245 evidence: an 866-line script copied in sight-unseen.
            "cp /tmp/scratch/recorder.py /work/dx/repo/docs/qa/recorder.py",
            "cp /tmp/scratch/narration.json /work/dx/repo/docs/qa/segment-1.json",
            # Relative destinations resolve against the working tree.
            "cp /tmp/scratch/thing.py docs/qa/thing.py",
            "mv /tmp/staged.md docs/notes.md",
            # tee and touch write every non-flag operand.
            "tee docs/out.txt",
            "touch src/dev10x/new_module.py",
            # A non-value flag is skipped without consuming the next token.
            "cp -r /tmp/scratch/dir docs/qa/dir",
            # -t inverts the positional rule: the flag's value is the
            # destination and every operand is a source.
            "cp -t docs/qa /tmp/scratch/recorder.py",
            "mv -t src/dev10x /tmp/a.py /tmp/b.py",
            "install -t docs/qa -m 644 /tmp/a.conf",
            # The --flag=value form arrives as a single token.
            "cp --target-directory=docs/qa /tmp/scratch/thing.py",
            "install -m 644 /tmp/a.conf /work/dx/repo/etc/a.conf",
            # A writer anywhere in a pipeline still writes.
            "cat /tmp/body.md | tee docs/body.md",
            "echo hi && cp /tmp/x docs/x",
            # A writer hidden in a command substitution still writes —
            # the same evasion DX003 already closes.
            "out=$(cp /tmp/x docs/x)",
            'echo "$(tee docs/x)"',
            "result=`cp /tmp/x docs/x`",
            # `..` must be normalised before comparing, or a traversal
            # that lands back inside the tree reads as outside.
            "cp /tmp/x docs/../src/x",
        ],
    )
    def test_denies_destination_inside_working_tree(
        self,
        validator: WriteDestinationValidator,
        command: str,
    ) -> None:
        result = validator.validate(_make_input(command=command))

        assert isinstance(result, HookResult)

    def test_denial_names_the_destination_and_the_alternative(
        self,
        validator: WriteDestinationValidator,
    ) -> None:
        result = validator.validate(
            _make_input(command="cp /tmp/scratch/recorder.py docs/qa/recorder.py")
        )

        assert isinstance(result, HookResult)
        assert "docs/qa/recorder.py" in result.message
        assert "`Write`" in result.message

    def test_denial_carries_the_rule_id(
        self,
        validator: WriteDestinationValidator,
    ) -> None:
        result = validator.validate(_make_input(command="cp /tmp/x docs/x"))

        assert isinstance(result, HookResult)
        assert result.rule_id == "DX017"


class TestLeavesWritesOutsideTheWorkingTreeAlone:
    @pytest.fixture()
    def validator(self, synthetic_root: None) -> WriteDestinationValidator:
        return WriteDestinationValidator()

    @pytest.mark.parametrize(
        "command",
        [
            # Scratch-to-scratch staging is legitimate shell work.
            "cp /tmp/a.py /tmp/b.py",
            "mv /tmp/Dev10x/staged.json /tmp/Dev10x/final.json",
            "touch /tmp/Dev10x/marker",
            "tee /tmp/out.txt",
            # A sibling checkout is not this working tree.
            "cp /tmp/x /work/dx/other-repo/docs/x",
            # `~` and `$VAR` are absolute once expanded; expanding them is
            # not this validator's guess to make.
            "cp /tmp/x ~/.claude/tools/x.py",
            "cp /tmp/x $HOME/notes.md",
            # The working-tree root itself is not a file destination.
            "touch /work/dx/repo",
            # Reads and non-writers are untouched.
            "cat docs/x",
            "rg -n pattern docs/",
            # A lone cp operand names a source with no destination.
            "cp docs/x",
            # A -t target outside the tree is fine even when the sources
            # are inside it — the sources are only read.
            "cp -t /tmp/Dev10x docs/x docs/y",
            "cp --target-directory=/tmp/Dev10x docs/x",
        ],
    )
    def test_abstains(
        self,
        validator: WriteDestinationValidator,
        command: str,
    ) -> None:
        assert validator.validate(_make_input(command=command)) is None

    def test_traversal_escaping_the_tree_is_outside(
        self,
        validator: WriteDestinationValidator,
    ) -> None:
        result = validator.validate(_make_input(command="cp /tmp/x docs/../../elsewhere/x"))

        assert result is None

    def test_flag_values_are_not_mistaken_for_paths(
        self,
        validator: WriteDestinationValidator,
    ) -> None:
        """``-m 644``'s value must not be read as the destination."""
        result = validator.validate(_make_input(command="install -m 644 /tmp/a /tmp/b"))

        assert result is None

    def test_an_inline_non_target_flag_value_is_not_a_path(
        self,
        validator: WriteDestinationValidator,
    ) -> None:
        """``--mode=644`` partitions on ``=`` but is not a target flag."""
        result = validator.validate(_make_input(command="install --mode=644 /tmp/a /tmp/b"))

        assert result is None


class TestWorkingTreeIsTheCheckoutNotTheCwd:
    """``cwd`` is the caller's directory, which may be a subdirectory."""

    @pytest.fixture()
    def validator(self) -> WriteDestinationValidator:
        return WriteDestinationValidator()

    @pytest.fixture()
    def checkout(self, tmp_path: Path) -> Path:
        """A worktree-shaped checkout: ``.git`` is a file, not a directory."""
        root = tmp_path / "repo"
        (root / "skills" / "foo").mkdir(parents=True)
        (root / "src").mkdir()
        (root / ".git").write_text("gitdir: /elsewhere\n", encoding="utf-8")
        return root

    def test_a_sibling_path_inside_the_repo_is_caught_from_a_nested_cwd(
        self,
        validator: WriteDestinationValidator,
        checkout: Path,
    ) -> None:
        """Reading cwd as the root would let this through — it is in the repo."""
        result = validator.validate(
            _make_input(
                command=f"cp /tmp/x {checkout}/src/bar.py",
                cwd=str(checkout / "skills" / "foo"),
            )
        )

        assert isinstance(result, HookResult)

    def test_a_relative_write_from_a_nested_cwd_is_caught(
        self,
        validator: WriteDestinationValidator,
        checkout: Path,
    ) -> None:
        result = validator.validate(
            _make_input(command="cp /tmp/x bar.py", cwd=str(checkout / "skills" / "foo"))
        )

        assert isinstance(result, HookResult)

    def test_outside_the_checkout_is_still_allowed_from_a_nested_cwd(
        self,
        validator: WriteDestinationValidator,
        checkout: Path,
    ) -> None:
        result = validator.validate(
            _make_input(command="cp /tmp/x /tmp/y", cwd=str(checkout / "skills" / "foo"))
        )

        assert result is None

    def test_a_cwd_in_no_checkout_falls_back_to_the_cwd_itself(
        self,
        validator: WriteDestinationValidator,
        tmp_path: Path,
    ) -> None:
        """Without a .git anywhere above, cwd is the best available root."""
        plain = tmp_path / "not-a-repo"
        plain.mkdir()

        result = validator.validate(_make_input(command="cp /tmp/x thing.py", cwd=str(plain)))

        assert isinstance(result, HookResult)


class TestShouldRun:
    @pytest.fixture()
    def validator(self) -> WriteDestinationValidator:
        return WriteDestinationValidator()

    def test_runs_when_a_writer_verb_is_present(
        self,
        validator: WriteDestinationValidator,
    ) -> None:
        assert validator.should_run(_make_input(command="cp /tmp/x docs/x")) is True

    def test_skips_when_no_writer_verb_is_present(
        self,
        validator: WriteDestinationValidator,
    ) -> None:
        assert validator.should_run(_make_input(command="git status")) is False

    def test_skips_when_cwd_is_unknown(
        self,
        validator: WriteDestinationValidator,
    ) -> None:
        """Without a working tree there is nothing to be inside of."""
        assert validator.should_run(_make_input(command="cp /tmp/x docs/x", cwd="")) is False


class TestMalformedInput:
    @pytest.fixture()
    def validator(self, synthetic_root: None) -> WriteDestinationValidator:
        return WriteDestinationValidator()

    def test_unbalanced_quotes_still_get_checked(
        self,
        validator: WriteDestinationValidator,
    ) -> None:
        """Abstaining on bad quoting would hand back an evasion.

        ``split_tokens`` falls back to whitespace splitting for exactly
        this reason — under-tokenizing is the dangerous direction for a
        validator that blocks.
        """
        result = validator.validate(_make_input(command="cp /tmp/x 'docs/x"))

        assert isinstance(result, HookResult)

    def test_an_empty_segment_names_no_destination(self) -> None:
        """Defensive guard — ``_segments`` filters blanks, so this is direct."""
        assert _destinations(segment="") == ("", [])
