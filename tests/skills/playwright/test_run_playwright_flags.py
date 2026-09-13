"""GH-1263: the per-run knobs must be expressible as flags.

An env prefix (`STAGING_URL=… run-playwright.sh …`) and a trailing
`| tail -40` each move the command string away from the allow rule that
covers the script path, so a preview-host probe prompts every time. These
tests pin the flag forms, their precedence over the environment, and that
`--tail` does not swallow a failing exit status.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

RUNNER = (
    Path(__file__).resolve().parents[3] / "skills" / "playwright" / "scripts" / "run-playwright.sh"
)

SECRETS = "CF_ACCESS_CLIENT_ID=id\nCF_ACCESS_CLIENT_SECRET=secret\nCRM_PASSWORD=pw\n"


@pytest.fixture
def secrets_file(tmp_path: Path) -> Path:
    path = tmp_path / "settings.secrets.env"
    path.write_text(SECRETS)
    return path


@pytest.fixture
def probe(tmp_path: Path) -> Path:
    path = tmp_path / "probe.py"
    path.write_text("print('probe')\n")
    return path


def run(
    *args: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(RUNNER), *args],
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, **(env or {})},
    )


class TestSecretsFileFlag:
    def test_flag_selects_the_secrets_file(self, secrets_file: Path, probe: Path):
        result = run(str(probe), "--secrets-file", str(secrets_file), "--validate-only")

        assert result.returncode == 0, result.stderr
        assert f"Secrets:  {secrets_file}" in result.stdout

    def test_flag_wins_over_the_environment(
        self,
        secrets_file: Path,
        probe: Path,
        tmp_path: Path,
    ):
        ignored = tmp_path / "ignored.env"
        ignored.write_text(SECRETS)

        result = run(
            str(probe),
            "--secrets-file",
            str(secrets_file),
            "--validate-only",
            env={"PLAYWRIGHT_SECRETS_FILE": str(ignored)},
        )

        assert f"Secrets:  {secrets_file}" in result.stdout

    def test_environment_still_works_without_the_flag(
        self,
        secrets_file: Path,
        probe: Path,
    ):
        result = run(
            str(probe),
            "--validate-only",
            env={"PLAYWRIGHT_SECRETS_FILE": str(secrets_file)},
        )

        assert result.returncode == 0, result.stderr
        assert f"Secrets:  {secrets_file}" in result.stdout


class TestStagingUrlFlag:
    def test_flag_sets_the_base_url(self, secrets_file: Path, probe: Path):
        result = run(
            str(probe),
            "--secrets-file",
            str(secrets_file),
            "--staging-url",
            "https://preview-abc.example.app",
            "--validate-only",
        )

        assert "Base URL: https://preview-abc.example.app" in result.stdout

    def test_flag_wins_over_the_environment(self, secrets_file: Path, probe: Path):
        result = run(
            str(probe),
            "--secrets-file",
            str(secrets_file),
            "--staging-url",
            "https://from-flag.example.app",
            "--validate-only",
            env={"STAGING_URL": "https://from-env.example.app"},
        )

        assert "Base URL: https://from-flag.example.app" in result.stdout

    def test_environment_still_works_without_the_flag(
        self,
        secrets_file: Path,
        probe: Path,
    ):
        result = run(
            str(probe),
            "--secrets-file",
            str(secrets_file),
            "--validate-only",
            env={"STAGING_URL": "https://from-env.example.app"},
        )

        assert "Base URL: https://from-env.example.app" in result.stdout

    def test_neither_leaves_the_documented_default(
        self,
        secrets_file: Path,
        probe: Path,
    ):
        result = run(
            str(probe),
            "--secrets-file",
            str(secrets_file),
            "--validate-only",
            env={"STAGING_URL": ""},
        )

        assert "Base URL: https://staging-app.example.com" in result.stdout


class TestTailFlag:
    """`--tail` replaces `| tail -40`, so it has to behave like the pipe did
    for the output and unlike it for the exit status."""

    @pytest.fixture
    def fake_uv(self, tmp_path: Path) -> Path:
        """A stand-in for `uv run`, so the tail path is exercised without
        resolving playwright or launching a browser."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        uv = bin_dir / "uv"
        uv.write_text(
            "#!/usr/bin/env bash\n"
            'for i in $(seq 1 100); do echo "line $i"; done\n'
            'exit "${FAKE_UV_STATUS:-0}"\n'
        )
        uv.chmod(uv.stat().st_mode | stat.S_IXUSR)
        return bin_dir

    def test_only_the_last_lines_are_printed(
        self,
        secrets_file: Path,
        probe: Path,
        fake_uv: Path,
    ):
        result = run(
            str(probe),
            "--secrets-file",
            str(secrets_file),
            "--tail",
            "5",
            env={"PATH": f"{fake_uv}:{os.environ['PATH']}"},
        )

        assert result.returncode == 0, result.stderr
        assert "line 100" in result.stdout
        assert "line 96" in result.stdout
        assert "line 95" not in result.stdout

    def test_a_failing_run_still_fails(
        self,
        secrets_file: Path,
        probe: Path,
        fake_uv: Path,
    ):
        result = run(
            str(probe),
            "--secrets-file",
            str(secrets_file),
            "--tail",
            "5",
            env={"PATH": f"{fake_uv}:{os.environ['PATH']}", "FAKE_UV_STATUS": "3"},
        )

        assert result.returncode == 3
        assert "line 100" in result.stdout

    def test_omitting_tail_prints_everything(
        self,
        secrets_file: Path,
        probe: Path,
        fake_uv: Path,
    ):
        result = run(
            str(probe),
            "--secrets-file",
            str(secrets_file),
            env={"PATH": f"{fake_uv}:{os.environ['PATH']}"},
        )

        assert result.returncode == 0, result.stderr
        assert "line 1\n" in result.stdout
        assert "line 100" in result.stdout

    @pytest.mark.parametrize("value", ["abc", "0", "-5"])
    def test_a_non_positive_count_is_refused(
        self,
        secrets_file: Path,
        probe: Path,
        value: str,
    ):
        result = run(
            str(probe),
            "--secrets-file",
            str(secrets_file),
            "--tail",
            value,
            "--validate-only",
        )

        assert result.returncode == 1
        assert "--tail takes a positive number of lines" in result.stderr


class TestUsage:
    def test_usage_names_the_new_flags(self):
        result = run("--validate-only")

        assert result.returncode == 1
        assert "--staging-url" in result.stderr
        assert "--secrets-file" in result.stderr
        assert "--tail" in result.stderr
