from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from dev10x.comm.chatbus.unit import (
    ENABLE_COMMANDS,
    RESTART_COMMAND,
    UNIT_NAME,
    InstalledUnit,
    UnitChange,
    install_unit,
    render_unit,
    service_state,
    user_unit_dir,
)
from tests.comm.chatbus.factories import expect_error, unwrap

EXEC = "/home/me/.local/bin/dev10x"


@pytest.fixture
def unit_dir(tmp_path: Path) -> Path:
    return tmp_path / "config-home" / "systemd" / "user"


class TestRenderUnit:
    @pytest.fixture
    def content(self) -> str:
        return render_unit(exec_start=EXEC)

    @pytest.mark.parametrize(
        "line",
        [
            "Type=simple",
            f"ExecStart={EXEC} chatbus run",
            "ExecReload=/bin/kill -HUP $MAINPID",
            "Restart=on-failure",
            "WantedBy=default.target",
        ],
    )
    def test_carries_the_d9_settings(self, content: str, line: str) -> None:
        assert line in content.splitlines()

    @pytest.mark.parametrize("forbidden", ["PassEnvironment", "Environment", "EnvironmentFile"])
    def test_passes_no_environment(self, content: str, forbidden: str) -> None:
        assert f"{forbidden}=" not in content


class TestUserUnitDir:
    def test_follows_xdg_config_home(self, tmp_path: Path) -> None:
        found = user_unit_dir(environ={"XDG_CONFIG_HOME": str(tmp_path)}, home=Path("/home/me"))
        assert found == tmp_path / "systemd" / "user"

    @pytest.mark.parametrize("environ", [{}, {"XDG_CONFIG_HOME": ""}])
    def test_defaults_under_home(self, environ: dict[str, str]) -> None:
        found = user_unit_dir(environ=environ, home=Path("/home/me"))
        assert found == Path("/home/me/.config/systemd/user")


class TestInstallUnit:
    @pytest.fixture
    def first(self, unit_dir: Path) -> InstalledUnit:
        return unwrap(install_unit(unit_dir=unit_dir, content=render_unit(exec_start=EXEC)))

    def test_creates_the_unit_file(self, first: InstalledUnit, unit_dir: Path) -> None:
        assert (first.change, first.path) == (UnitChange.CREATED, unit_dir / UNIT_NAME)
        assert first.path.read_text() == render_unit(exec_start=EXEC)

    def test_tells_the_user_how_to_enable_it(self, first: InstalledUnit) -> None:
        assert first.next_steps == ENABLE_COMMANDS
        assert "systemctl --user enable --now dev10x-chatbus.service" in first.next_steps

    def test_a_second_run_changes_nothing(self, first: InstalledUnit, unit_dir: Path) -> None:
        mtime = first.path.stat().st_mtime_ns
        again = unwrap(install_unit(unit_dir=unit_dir, content=render_unit(exec_start=EXEC)))
        assert again.change is UnitChange.UNCHANGED
        assert first.path.stat().st_mtime_ns == mtime
        assert sorted(path.name for path in unit_dir.iterdir()) == [UNIT_NAME]

    def test_a_changed_unit_is_updated_and_needs_a_restart(
        self, first: InstalledUnit, unit_dir: Path
    ) -> None:
        moved = render_unit(exec_start="/opt/dev10x")
        updated = unwrap(install_unit(unit_dir=unit_dir, content=moved))
        assert updated.change is UnitChange.UPDATED
        assert updated.next_steps[-1] == RESTART_COMMAND
        assert first.path.read_text() == moved


def test_an_unwritable_unit_dir_is_an_error(tmp_path: Path) -> None:
    blocked = tmp_path / "systemd"
    blocked.write_text("not a directory")
    failed = install_unit(unit_dir=blocked / "user", content="x")
    assert "Cannot write the Chat bus unit" in expect_error(failed).error


class FakeSystemctl:
    def __init__(self, *, stdout: str = "", returncode: int = 0, raises: Exception | None = None):
        self.stdout = stdout
        self.returncode = returncode
        self.raises = raises
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        if self.raises is not None:
            raise self.raises
        return subprocess.CompletedProcess(
            args=args, returncode=self.returncode, stdout=self.stdout, stderr=""
        )


class TestServiceState:
    def test_asks_systemctl_about_the_unit_only(self) -> None:
        systemctl = FakeSystemctl(stdout="active\n")
        assert service_state(runner=systemctl) == "active"
        assert systemctl.calls == [["systemctl", "--user", "is-active", UNIT_NAME]]

    @pytest.mark.parametrize(
        ("systemctl", "expected"),
        [
            (FakeSystemctl(stdout="", returncode=4), "unknown (exit 4)"),
            (FakeSystemctl(raises=FileNotFoundError()), "unknown (systemctl not found)"),
            (
                FakeSystemctl(raises=subprocess.TimeoutExpired(cmd="systemctl", timeout=10)),
                "unknown (systemctl did not answer in 10s)",
            ),
        ],
    )
    def test_reports_unknown_when_systemctl_cannot_say(
        self, systemctl: FakeSystemctl, expected: str
    ) -> None:
        assert service_state(runner=systemctl) == expected
