"""Tests for the unified dispatcher entry point."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

DISPATCHER = (
    Path(__file__).resolve().parent.parent.parent
    / "hooks"
    / "scripts"
    / "validate-bash-command.py"
)


def _run_hook(*, tool_name: str, command: str) -> subprocess.CompletedProcess[str]:
    payload = json.dumps({"tool_name": tool_name, "tool_input": {"command": command}})
    return subprocess.run(
        [sys.executable, str(DISPATCHER)],
        input=payload,
        capture_output=True,
        text=True,
        cwd=str(DISPATCHER.parent),
    )


class TestDispatcherPassThrough:
    def test_allows_simple_git_command(self) -> None:
        result = _run_hook(tool_name="Bash", command="git status")
        assert result.returncode == 0

    def test_ignores_non_bash_tools(self) -> None:
        result = _run_hook(tool_name="Read", command="anything")
        assert result.returncode == 0

    def test_allows_empty_command(self) -> None:
        result = _run_hook(tool_name="Bash", command="")
        assert result.returncode == 0


class TestDispatcherBlocking:
    def test_blocks_env_prefix_git(self) -> None:
        result = _run_hook(
            tool_name="Bash",
            command="GIT_SEQUENCE_EDITOR=true git rebase -i HEAD~3",
        )
        assert result.returncode == 2

    def test_blocks_shell_write(self) -> None:
        result = _run_hook(
            tool_name="Bash",
            command="cat > /tmp/file.txt",
        )
        assert result.returncode == 2

    def test_blocks_python3_inline(self) -> None:
        result = _run_hook(
            tool_name="Bash",
            command='python3 -c "print(1)"',
        )
        assert result.returncode == 2

    def test_blocks_implementation_verb_commit(self) -> None:
        result = _run_hook(
            tool_name="Bash",
            command='git commit -m "Add new feature"',
        )
        assert result.returncode == 2

    def test_blocks_jtbd_verb_commit_with_m_flag(self) -> None:
        result = _run_hook(
            tool_name="Bash",
            command='git commit -m "Enable new feature"',
        )
        assert result.returncode == 2
        assert "Dev10x:git-commit" in result.stderr

    def test_allows_commit_with_skill_temp_f_flag(self) -> None:
        result = _run_hook(
            tool_name="Bash",
            command="git commit -F /tmp/Dev10x/git/commit-msg.W9DryMXsQ5Aw.txt",
        )
        assert result.returncode == 0

    def test_allows_commit_with_any_file_under_git_namespace(self) -> None:
        result = _run_hook(
            tool_name="Bash",
            command="git commit -F /tmp/Dev10x/git/msg.txt",
        )
        assert result.returncode == 0


MONITOR_PR_WATCH_LOOP = """
prev=""
while true; do
  s=$(gh pr view 1234 --repo owner/repo --json state,mergedAt,reviewDecision \
2>/dev/null) || { sleep 300; continue; }
  cur=$(jq -r ".state" <<<"$s" 2>/dev/null) || cur=""
  if [ -n "$cur" ] && [ "$cur" != "$prev" ] && [ -n "$prev" ]; then echo "$cur"; fi
  [ -n "$cur" ] && prev="$cur"
  if jq -e '.state=="MERGED"' <<<"$s" >/dev/null 2>&1; then break; fi
  sleep 300
done
"""

BARE_WATCH_LOOP = """\
while true; do
  curl -sf https://example.test/ready && break
  sleep 30
done"""


class TestMonitorToolReachesTheChain:
    """A Monitor command is a Bash command (GH-1211, GH-1212).

    hooks.json has registered the ``Monitor`` matcher since GH-1138, but
    the entry point discarded every payload whose ``tool_name`` was not
    ``Bash`` before any validator ran — so the registration was inert and
    a poll loop routed through Monitor reached the supervisor as a raw
    permission prompt no allow rule could answer.
    """

    def test_blocks_the_field_reported_pr_watch_loop(self) -> None:
        result = _run_hook(tool_name="Monitor", command=MONITOR_PR_WATCH_LOOP)
        assert result.returncode == 2

    def test_blocks_a_bare_while_sleep_loop_naming_no_pr_command(self) -> None:
        """The defect is the loop, not the payload command (GH-1212).

        Two gaps had to close for this to block: the loop patterns were
        single-line (no `sleep` several lines below `do` could match), and
        `skill_redirect.should_run`'s fast-path token filter dropped any
        command naming none of `commit`/`push`/`checks`/… before the
        engine ran.
        """
        result = _run_hook(tool_name="Monitor", command=BARE_WATCH_LOOP)
        assert result.returncode == 2

    def test_bare_watch_loop_names_the_rule_not_a_raw_regex(self) -> None:
        result = _run_hook(tool_name="Monitor", command=BARE_WATCH_LOOP)
        assert "watch-loop-handrolled" in result.stderr
        assert r"\bsleep\b" not in result.stderr

    def test_bare_watch_loop_renders_every_alternative(self) -> None:
        """`use-alternative` rules used to emit a bare `Skill()` (GH-1212)."""
        result = _run_hook(tool_name="Monitor", command=BARE_WATCH_LOOP)
        assert "Skill()" not in result.stderr
        assert "run_in_background" in result.stderr
        assert "dev10x foreman watch" in result.stderr

    def test_blocks_a_multiline_until_sleep_loop(self) -> None:
        result = _run_hook(
            tool_name="Monitor",
            command="until [ -f /tmp/ready ]; do\n  echo waiting\n  sleep 10\ndone",
        )
        assert result.returncode == 2

    def test_blocks_the_same_loop_submitted_as_bash(self) -> None:
        """Routing through Monitor must not be the cheaper path."""
        result = _run_hook(tool_name="Bash", command=MONITOR_PR_WATCH_LOOP)
        assert result.returncode == 2

    def test_allows_a_benign_monitor_command(self) -> None:
        result = _run_hook(tool_name="Monitor", command="git status")
        assert result.returncode == 0

    def test_allows_an_empty_monitor_command(self) -> None:
        result = _run_hook(tool_name="Monitor", command="")
        assert result.returncode == 0
