"""Tests for `dev10x skill notify` subcommands (GH-313)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from dev10x.cli import cli


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


class TestPluginRoot:
    def test_plugin_root_resolves_to_repo_root(self) -> None:
        from dev10x.commands.skill import _plugin_root

        root = _plugin_root()

        assert (root / "skills").is_dir(), f"skills/ not under {root}"
        assert (root / "src" / "dev10x" / "commands" / "skill.py").is_file()


class TestNotifyGroupRegistration:
    def test_notify_group_exposed(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["skill", "notify", "--help"])

        assert result.exit_code == 0
        assert "slack-review-prepare" in result.output
        assert "slack-send" in result.output

    def test_slack_review_prepare_help(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            ["skill", "notify", "slack-review-prepare", "--help"],
        )

        assert result.exit_code == 0
        assert "--pr" in result.output
        assert "--repo" in result.output

    def test_slack_send_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["skill", "notify", "slack-send", "--help"])

        assert result.exit_code == 0
        assert "--channel" in result.output
        assert "--message" in result.output
        assert "--message-file" in result.output
        assert "--thread-ts" in result.output
        assert "--workspace" in result.output


class TestSlackReviewPrepare:
    def test_delegates_to_cmd_prepare(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, object] = {}

        def fake_cmd_prepare(args: object) -> None:
            captured["pr"] = args.pr  # type: ignore[attr-defined]
            captured["repo"] = args.repo  # type: ignore[attr-defined]

        from dev10x.skills.notifications import slack_review_request

        monkeypatch.setattr(slack_review_request, "cmd_prepare", fake_cmd_prepare)

        result = runner.invoke(
            cli,
            ["skill", "notify", "slack-review-prepare", "--pr", "42", "--repo", "org/r"],
        )

        assert result.exit_code == 0, result.output
        assert captured == {"pr": 42, "repo": "org/r"}


class TestSlackSend:
    def test_requires_message_or_file(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            ["skill", "notify", "slack-send", "--channel", "C123"],
        )

        assert result.exit_code != 0
        assert "Provide --message or --message-file" in result.output

    def test_invokes_slack_notify_script(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        fake_script = tmp_path / "slack-notify.py"
        fake_script.write_text("#!/usr/bin/env python\n")

        from dev10x.commands import skill as skill_module

        monkeypatch.setattr(
            skill_module,
            "_plugin_root",
            lambda: tmp_path.parent,
        )
        (tmp_path.parent / "skills" / "slack").mkdir(parents=True, exist_ok=True)
        real_script = tmp_path.parent / "skills" / "slack" / "slack-notify.py"
        real_script.write_text("#!/usr/bin/env python\n")

        captured_cmd: list[list[str]] = []

        def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            captured_cmd.append(cmd)
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=0,
                stdout="✅ Slack message sent",
                stderr="",
            )

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = runner.invoke(
            cli,
            [
                "skill",
                "notify",
                "slack-send",
                "--channel",
                "C123",
                "--message",
                "hello",
                "--thread-ts",
                "1.2",
                "--workspace",
                "aperture",
            ],
        )

        assert result.exit_code == 0, result.output
        assert "Slack message sent" in result.output
        assert captured_cmd, "subprocess.run was not invoked"
        cmd = captured_cmd[0]
        assert cmd[0] == str(real_script)
        assert "--channel" in cmd and "C123" in cmd
        assert "--message" in cmd and "hello" in cmd
        assert "--thread-ts" in cmd and "1.2" in cmd
        assert "--workspace" in cmd and "aperture" in cmd

    def test_passes_message_file_through(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        from dev10x.commands import skill as skill_module

        monkeypatch.setattr(skill_module, "_plugin_root", lambda: tmp_path)
        slack_dir = tmp_path / "skills" / "slack"
        slack_dir.mkdir(parents=True, exist_ok=True)
        (slack_dir / "slack-notify.py").write_text("#!/usr/bin/env python\n")

        msg_file = tmp_path / "msg.txt"
        msg_file.write_text("hello from file")

        captured_cmd: list[list[str]] = []

        def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            captured_cmd.append(cmd)
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = runner.invoke(
            cli,
            [
                "skill",
                "notify",
                "slack-send",
                "--channel",
                "C123",
                "--message-file",
                str(msg_file),
            ],
        )

        assert result.exit_code == 0, result.output
        assert "--message-file" in captured_cmd[0]
        assert str(msg_file) in captured_cmd[0]

    def test_propagates_nonzero_exit_code(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        from dev10x.commands import skill as skill_module

        monkeypatch.setattr(skill_module, "_plugin_root", lambda: tmp_path.parent)
        slack_dir = tmp_path.parent / "skills" / "slack"
        slack_dir.mkdir(parents=True, exist_ok=True)
        (slack_dir / "slack-notify.py").write_text("#!/usr/bin/env python\n")

        def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=2,
                stdout="",
                stderr="missing_scope",
            )

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = runner.invoke(
            cli,
            ["skill", "notify", "slack-send", "--channel", "C123", "--message", "x"],
        )

        assert result.exit_code == 2

    def test_missing_slack_notify_script(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        from dev10x.commands import skill as skill_module

        monkeypatch.setattr(skill_module, "_plugin_root", lambda: tmp_path / "missing")

        result = runner.invoke(
            cli,
            ["skill", "notify", "slack-send", "--channel", "C123", "--message", "x"],
        )

        assert result.exit_code == 1
        assert "slack-notify.py not found" in result.output
