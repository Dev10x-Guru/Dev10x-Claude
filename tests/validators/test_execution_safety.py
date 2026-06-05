"""Tests for ExecutionSafetyValidator."""

from __future__ import annotations

import pytest

from dev10x.validators.execution_safety import (
    INPLACE_EDIT_MSG,
    SHELL_INTERP_MSG,
    ExecutionSafetyValidator,
)
from tests.fakers import BashHookInputFaker


def _make_input(*, command: str) -> BashHookInputFaker:
    return BashHookInputFaker.build(
        command=command,
    )


class TestShellWrites:
    @pytest.fixture()
    def validator(self) -> ExecutionSafetyValidator:
        return ExecutionSafetyValidator()

    @pytest.mark.parametrize(
        "command",
        [
            "cat > /tmp/file.txt",
            "cat << EOF > /tmp/file.txt",
            "echo hello > /tmp/file.txt",
            "echo hello >> /tmp/file.txt",
            "printf '%s' hello > /tmp/file.txt",
        ],
    )
    def test_blocks_shell_write_redirects(
        self, validator: ExecutionSafetyValidator, command: str
    ) -> None:
        inp = _make_input(command=command)
        result = validator.validate(inp=inp)
        assert result is not None
        assert "Write/Edit tool" in result.message

    def test_allows_cat_without_redirect(self, validator: ExecutionSafetyValidator) -> None:
        inp = _make_input(command="cat /tmp/file.txt")
        result = validator.validate(inp=inp)
        assert result is None


class TestPython3Inline:
    @pytest.fixture()
    def validator(self) -> ExecutionSafetyValidator:
        return ExecutionSafetyValidator()

    def test_blocks_python3_c(self, validator: ExecutionSafetyValidator) -> None:
        inp = _make_input(command='python3 -c "print(1)"')
        result = validator.validate(inp=inp)
        assert result is not None
        assert "python3" in result.message.lower()

    def test_allows_python3_module(self, validator: ExecutionSafetyValidator) -> None:
        inp = _make_input(command="python3 -m json.tool input.json")
        result = validator.validate(inp=inp)
        assert result is None

    def test_allows_approved_path(self, validator: ExecutionSafetyValidator) -> None:
        inp = _make_input(command="python3 ~/.claude/tools/script.py")
        result = validator.validate(inp=inp)
        assert result is None

    def test_blocks_untrusted_abs_path(self, validator: ExecutionSafetyValidator) -> None:
        inp = _make_input(command="python3 /tmp/malicious.py")
        result = validator.validate(inp=inp)
        assert result is not None

    def test_allows_relative_path(self, validator: ExecutionSafetyValidator) -> None:
        inp = _make_input(command="python3 manage.py runserver")
        result = validator.validate(inp=inp)
        assert result is None


class TestInplaceEdit:
    @pytest.fixture()
    def validator(self) -> ExecutionSafetyValidator:
        return ExecutionSafetyValidator()

    # --- Positive cases: in-place edits that must be blocked ---

    @pytest.mark.parametrize(
        "command",
        [
            # sed -i basic forms
            "sed -i 's/a/b/' file.txt",
            "sed -i.bak 's/a/b/' file.txt",
            # Combined short flags containing 'i'
            "sed -ni 's/a/b/' file.txt",
            "sed -in 's/a/b/' file.txt",
            "sed -in.bak 's/a/b/' file.txt",
            "sed -i.bak -e 's/a/b/' file.txt",
            # perl -i forms
            "perl -i -pe 's/a/b/' file.txt",
            "perl -pi -e 's/a/b/' file.txt",
            "perl -pi.bak -e 's/a/b/' file.txt",
            "perl -i.bak -pe 's/a/b/' file.txt",
            # gawk -i inplace
            "gawk -i inplace '{print}' file.txt",
            "awk -i inplace '{print}' file.txt",
            # dd of= writing to a real file
            "dd if=/dev/urandom of=/tmp/file.bin bs=1M count=1",
            "dd if=input.img of=output.img",
        ],
    )
    def test_blocks_inplace_edit(self, validator: ExecutionSafetyValidator, command: str) -> None:
        inp = _make_input(command=command)
        result = validator.validate(inp=inp)
        assert result is not None
        assert result.message == INPLACE_EDIT_MSG

    def test_blocks_inplace_edit_in_pipeline(self, validator: ExecutionSafetyValidator) -> None:
        inp = _make_input(command="cat file.txt | sed -i 's/a/b/' -")
        result = validator.validate(inp=inp)
        assert result is not None
        assert result.message == INPLACE_EDIT_MSG

    def test_blocks_env_prefix_stripped_sed(self, validator: ExecutionSafetyValidator) -> None:
        inp = _make_input(command="FOO=1 sed -i 's/a/b/' file.txt")
        result = validator.validate(inp=inp)
        assert result is not None
        assert result.message == INPLACE_EDIT_MSG

    def test_blocks_env_prefix_stripped_perl(self, validator: ExecutionSafetyValidator) -> None:
        inp = _make_input(command="LC_ALL=C perl -pi -e 's/foo/bar/' file.txt")
        result = validator.validate(inp=inp)
        assert result is not None
        assert result.message == INPLACE_EDIT_MSG

    # --- Negative cases: read-only / stdout forms that must NOT be flagged ---

    @pytest.mark.parametrize(
        "command",
        [
            # sed read-only
            "sed -n '1,5p' file.txt",
            "sed 's/a/b/' file.txt",
            "sed -e 's/a/b/' file.txt",
            "sed -E 's/a/b/' file.txt",
            # perl without -i
            "perl -ne 'print if /foo/' file.txt",
            "perl -pe 's/a/b/' file.txt",
            # awk without -i inplace
            "awk '{print}' file.txt",
            "awk -F, '{print $1}' file.txt",
            # gawk -i with something other than 'inplace'
            "gawk -i other_extension.awk '{print}' file.txt",
            # dd with no of= at all
            "dd if=/dev/zero bs=512 count=1",
            # dd of= pointing to /dev/null
            "dd if=/dev/zero of=/dev/null bs=1M count=1",
            # dd of= pointing to /dev/stdout
            "dd if=/dev/zero of=/dev/stdout bs=512 count=1",
        ],
    )
    def test_allows_readonly_forms(
        self, validator: ExecutionSafetyValidator, command: str
    ) -> None:
        inp = _make_input(command=command)
        result = validator.validate(inp=inp)
        assert result is None

    def test_returns_none_on_unbalanced_quotes(self, validator: ExecutionSafetyValidator) -> None:
        inp = _make_input(command="sed -i 's/a/b")
        result = validator.validate(inp=inp)
        assert result is None

    def test_allows_non_inplace_command_in_pipeline(
        self, validator: ExecutionSafetyValidator
    ) -> None:
        # A pipeline where neither segment is an in-place editor
        inp = _make_input(command="grep foo file.txt | sort")
        result = validator.validate(inp=inp)
        assert result is None

    def test_allows_empty_segment_after_env_strip(
        self, validator: ExecutionSafetyValidator
    ) -> None:
        # ENV=val alone (after stripping yields empty parts) in a pipeline segment
        inp = _make_input(command="grep foo file.txt | LC_ALL=C")
        result = validator.validate(inp=inp)
        assert result is None


class TestInplaceEditHelpers:
    """Unit tests for module-level helpers in execution_safety."""

    def test_has_inplace_flag_returns_false_for_unknown_cmd(self) -> None:
        from dev10x.validators.execution_safety import _has_inplace_flag

        assert _has_inplace_flag(argv=["-i", "file.txt"], cmd="unknown") is False

    def test_should_run_always_true(self) -> None:
        validator = ExecutionSafetyValidator()
        inp = _make_input(command="ls")
        assert validator.should_run(inp=inp) is True


class TestPython3InlineEdgeCases:
    @pytest.fixture()
    def validator(self) -> ExecutionSafetyValidator:
        return ExecutionSafetyValidator()

    def test_unbalanced_quotes_in_python3_check_returns_none(
        self, validator: ExecutionSafetyValidator
    ) -> None:
        # python3 is in the string but shlex.split will raise ValueError
        inp = _make_input(command="python3 -c 'print(\"hello)")
        result = validator.validate(inp=inp)
        assert result is None

    def test_python3_as_argument_not_command_returns_none(
        self, validator: ExecutionSafetyValidator
    ) -> None:
        # python3 appears in the string but the actual command is something else
        inp = _make_input(command="echo python3 rocks")
        result = validator.validate(inp=inp)
        assert result is None


class TestShellInterpreter:
    """GH-469: bash/sh/zsh are siblings of python3 in the interpreter guard."""

    @pytest.fixture()
    def validator(self) -> ExecutionSafetyValidator:
        return ExecutionSafetyValidator()

    # --- Positive cases: untrusted/inline shell execution must be blocked ---

    @pytest.mark.parametrize(
        "command",
        [
            "bash /tmp/x.sh",
            "sh /tmp/x.sh",
            "zsh /tmp/x.sh",
            "bash /tmp/classify_branches.sh",
        ],
    )
    def test_blocks_untrusted_abs_script(
        self, validator: ExecutionSafetyValidator, command: str
    ) -> None:
        inp = _make_input(command=command)
        result = validator.validate(inp=inp)
        assert result is not None
        assert result.message == SHELL_INTERP_MSG

    @pytest.mark.parametrize(
        "command",
        [
            "bash -c 'rm -rf /tmp/x'",
            "sh -c 'echo hi'",
            "zsh -c 'print hi'",
        ],
    )
    def test_blocks_inline_c(self, validator: ExecutionSafetyValidator, command: str) -> None:
        inp = _make_input(command=command)
        result = validator.validate(inp=inp)
        assert result is not None
        assert result.message == SHELL_INTERP_MSG

    def test_blocks_env_prefix_stripped_bash(self, validator: ExecutionSafetyValidator) -> None:
        inp = _make_input(command="FOO=1 bash /tmp/x.sh")
        result = validator.validate(inp=inp)
        assert result is not None
        assert result.message == SHELL_INTERP_MSG

    # --- Negative cases: approved / relative forms must NOT be flagged ---

    @pytest.mark.parametrize(
        "command",
        [
            "bash ~/.claude/tools/x.sh",
            "bash ~/.claude/skills/foo/run.sh",
            "bash ~/.claude/hooks/h.sh",
            "bash /tmp/Dev10x/x.sh",
            "sh /tmp/Dev10x/setup.sh",
            "zsh /tmp/Dev10x/run.zsh",
            "bash ./build.sh",
            "bash build.sh",
        ],
    )
    def test_allows_approved_and_relative(
        self, validator: ExecutionSafetyValidator, command: str
    ) -> None:
        inp = _make_input(command=command)
        result = validator.validate(inp=inp)
        assert result is None

    def test_unbalanced_quotes_returns_none(self, validator: ExecutionSafetyValidator) -> None:
        inp = _make_input(command="bash -c 'echo hi")
        result = validator.validate(inp=inp)
        assert result is None

    def test_interpreter_as_argument_returns_none(
        self, validator: ExecutionSafetyValidator
    ) -> None:
        # 'bash' appears only as an argument, not the command
        inp = _make_input(command="echo bash /tmp/x.sh")
        result = validator.validate(inp=inp)
        assert result is None

    def test_dev10x_tmp_not_approved_for_python3(
        self, validator: ExecutionSafetyValidator
    ) -> None:
        # /tmp/Dev10x/ is a shell-only carve-out; python3 keeps the narrow set
        inp = _make_input(command="python3 /tmp/Dev10x/x.py")
        result = validator.validate(inp=inp)
        assert result is not None
