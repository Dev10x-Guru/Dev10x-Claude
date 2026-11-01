"""Tests for `dev10x supervisor` (GH-1692)."""

from __future__ import annotations

import http.client
import stat
import threading
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from click.testing import CliRunner
from dev10x.domain.dev10x_paths import CONFIG_HOME_ENV_VAR, Dev10xConfigDir

from dev10x.cli import cli
from dev10x.comm.supervisor import paths
from dev10x.comm.supervisor.probes import Snapshot
from dev10x.commands import supervisor as command


@pytest.fixture
def config_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    home = tmp_path / "config"
    monkeypatch.setenv(CONFIG_HOME_ENV_VAR, str(home))
    Dev10xConfigDir.reset_cache()
    yield home
    Dev10xConfigDir.reset_cache()


def test_unit_prints_execstart() -> None:
    result = CliRunner().invoke(cli, ["supervisor", "unit", "--port", "9000"])

    assert ("supervisor serve --port 9000" in result.output, "[Install]" in result.output) == (
        True,
        True,
    )


def test_cli_lists_supervisor() -> None:
    assert "supervisor" in CliRunner().invoke(cli, ["--help"]).output


def test_write_token_mode_0600(tmp_path: Path) -> None:
    path = tmp_path / "supervisor" / "token"

    command.write_token(token="abc", path=path)

    assert (path.read_text(), stat.S_IMODE(path.stat().st_mode)) == ("abc\n", 0o600)


def test_build_app_uses_config_paths(config_home: Path, tmp_path: Path) -> None:
    app = command.build_app(
        kb_root=tmp_path / "kb",
        bus_root=tmp_path / "bus",
        relay_mailbox="relay",
        token="t",
    )

    assert (app.log_path, app.store.all(), app.relay_mailbox) == (
        paths.actions_log_path(),
        [],
        "relay",
    )


def test_build_app_keeps_dev_state_apart(config_home: Path, tmp_path: Path) -> None:
    app = command.build_app(
        kb_root=tmp_path / "kb",
        bus_root=tmp_path / "bus",
        relay_mailbox="relay",
        token="t",
        instance=paths.Instance.DEV,
    )

    assert (app.log_path, app.store._path) == (
        paths.actions_log_path(instance=paths.Instance.DEV),
        paths.decisions_path(instance=paths.Instance.DEV),
    )


def test_run_service_serves_until_stopped(config_home: Path, tmp_path: Path) -> None:
    app = command.build_app(
        kb_root=tmp_path / "kb", bus_root=tmp_path / "bus", relay_mailbox="relay", token="t"
    )
    stop = threading.Event()
    announced: list[str] = []
    ready = threading.Event()

    def announce(line: str) -> None:
        announced.append(line)
        ready.set()

    service = threading.Thread(
        daemon=True,
        target=command.run_service,
        kwargs={
            "app": app,
            "port": 0,
            "interval": 0.01,
            "stop": stop,
            "provider": lambda: Snapshot(sessions=[]),
            "announce": announce,
        },
    )
    service.start()
    try:
        ready.wait(timeout=5)
        url = urlsplit(announced[0].removeprefix("Supervisor page: "))
        connection = http.client.HTTPConnection("127.0.0.1", url.port, timeout=5)
        connection.request("GET", f"/api/sessions?{url.query}")
        status = connection.getresponse().status
        connection.close()
    finally:
        stop.set()
        service.join(timeout=5)

    assert (status, service.is_alive(), announced[0].endswith("/?token=t")) == (200, False, True)


def test_serve_wires_service(
    config_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def fake_run_service(**kwargs: object) -> None:
        seen.update(kwargs)

    monkeypatch.setattr(command, "run_service", fake_run_service)
    handlers: dict[int, object] = {}
    monkeypatch.setattr(
        command.signal, "signal", lambda signum, handler: handlers.update({signum: handler})
    )

    result = CliRunner().invoke(
        cli,
        ["supervisor", "serve", "--port", "0", "--bus-root", str(tmp_path / "bus")],
    )
    handlers[command.signal.SIGTERM](command.signal.SIGTERM, None)  # type: ignore[operator]
    app = seen["app"]
    on_disk = paths.token_path().read_text().strip()

    assert (
        result.exit_code,
        seen["port"],
        on_disk == app.hook_token,  # type: ignore[attr-defined]
        on_disk != app.token,  # type: ignore[attr-defined]
        seen["stop"].is_set(),  # type: ignore[attr-defined]
        set(handlers) == {command.signal.SIGTERM, command.signal.SIGINT},
        app.auto_rename,  # type: ignore[attr-defined]
    ) == (0, 0, True, True, True, True, True)


def test_serve_can_skip_the_start_rename(
    config_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}
    monkeypatch.setattr(command, "run_service", lambda **kwargs: seen.update(kwargs))
    monkeypatch.setattr(command.signal, "signal", lambda signum, handler: None)

    CliRunner().invoke(
        cli,
        ["supervisor", "serve", "--no-rename", "--port", "0", "--bus-root", str(tmp_path / "bus")],
    )

    assert seen["app"].auto_rename is False  # type: ignore[attr-defined]


def test_serve_defaults_to_the_release_port(
    config_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}
    monkeypatch.setattr(command, "run_service", lambda **kwargs: seen.update(kwargs))
    monkeypatch.setattr(command.signal, "signal", lambda signum, handler: None)

    CliRunner().invoke(cli, ["supervisor", "serve", "--bus-root", str(tmp_path / "bus")])

    assert seen["port"] == paths.DEFAULT_PORT


def test_dev_instance_defaults_to_the_dev_port(
    config_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}
    monkeypatch.setattr(command, "run_service", lambda **kwargs: seen.update(kwargs))
    monkeypatch.setattr(command.signal, "signal", lambda signum, handler: None)

    CliRunner().invoke(
        cli,
        ["supervisor", "serve", "--instance", "dev", "--bus-root", str(tmp_path / "bus")],
    )

    assert seen["port"] == paths.DEV_PORT


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    root = tmp_path / "Dev10x-Claude"
    root.mkdir()
    (root / "pyproject.toml").write_text('[project]\nname = "Dev10x"\n', encoding="utf-8")
    return root


@pytest.fixture
def pinned(config_home: Path, checkout: Path) -> Path:
    result = CliRunner().invoke(cli, ["supervisor", "dev", "pin", "--checkout", str(checkout)])
    assert result.exit_code == 0, result.output
    return checkout


class TestDevInstance:
    @pytest.fixture
    def serve_dev(
        self,
        config_home: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> list[dict[str, object]]:
        runs: list[dict[str, object]] = []
        monkeypatch.setattr(command, "run_service", lambda **kwargs: runs.append(kwargs))
        monkeypatch.setattr(command.signal, "signal", lambda signum, handler: None)
        for _ in range(2):
            CliRunner().invoke(
                cli,
                [
                    "supervisor",
                    "serve",
                    "--instance",
                    "dev",
                    "--port",
                    "9300",
                    "--bus-root",
                    str(tmp_path / "bus"),
                ],
            )
        return runs

    def test_page_token_survives_a_restart(self, serve_dev: list[dict[str, object]]) -> None:
        first, second = (run["app"].token for run in serve_dev)  # type: ignore[attr-defined]
        saved = paths.page_token_path(instance=paths.Instance.DEV)

        assert (first == second, saved.read_text().strip() == first) == (True, True)

    def test_page_token_file_is_private(self, serve_dev: list[dict[str, object]]) -> None:
        saved = paths.page_token_path(instance=paths.Instance.DEV)

        assert stat.S_IMODE(saved.stat().st_mode) == 0o600

    def test_hook_token_goes_to_the_dev_dir(self, serve_dev: list[dict[str, object]]) -> None:
        app = serve_dev[-1]["app"]

        assert (
            paths.token_path(instance=paths.Instance.DEV).read_text().strip(),
            paths.token_path().exists(),
        ) == (app.hook_token, False)  # type: ignore[attr-defined]

    def test_never_renames_sessions(self, serve_dev: list[dict[str, object]]) -> None:
        assert [run["app"].auto_rename for run in serve_dev] == [False, False]  # type: ignore[attr-defined]

    def test_uses_the_given_port(self, serve_dev: list[dict[str, object]]) -> None:
        assert serve_dev[0]["port"] == 9300

    def test_names_the_token_file_instead_of_the_token(
        self, serve_dev: list[dict[str, object]]
    ) -> None:
        assert serve_dev[0]["token_file"] == paths.page_token_path(instance=paths.Instance.DEV)


def test_dev_page_url_leaves_the_token_out_of_the_log(config_home: Path, tmp_path: Path) -> None:
    app = command.build_app(
        kb_root=tmp_path / "kb",
        bus_root=tmp_path / "bus",
        relay_mailbox="relay",
        token="secret-tok",
        instance=paths.Instance.DEV,
    )
    stop = threading.Event()
    stop.set()
    announced: list[str] = []

    command.run_service(
        app=app,
        port=0,
        interval=0.01,
        stop=stop,
        provider=lambda: Snapshot(sessions=[]),
        announce=announced.append,
        token_file=tmp_path / "page-token",
    )

    assert (
        "secret-tok" in announced[0],
        announced[0].endswith(f"(token in {tmp_path / 'page-token'})"),
    ) == (False, True)


def test_release_page_token_is_fresh_each_boot(config_home: Path) -> None:
    tokens = {command.page_token(instance=paths.Instance.RELEASE) for _ in range(2)}

    assert (len(tokens), paths.page_token_path().exists()) == (2, False)


class TestServeDev:
    def test_refuses_without_a_pin(self, config_home: Path) -> None:
        result = CliRunner().invoke(cli, ["supervisor", "serve", "--dev"])

        assert (result.exit_code, command.NOT_PINNED in result.output) == (1, True)

    def test_launches_the_checkout_code(
        self,
        pinned: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        seen: dict[str, object] = {}
        monkeypatch.setattr(command, "run_launcher", lambda **kwargs: seen.update(kwargs))
        monkeypatch.setattr(command.signal, "signal", lambda signum, handler: None)

        CliRunner().invoke(cli, ["supervisor", "serve", "--dev", "--uv", "/opt/uv"])
        launcher = seen["launcher"]

        assert (
            (
                launcher.checkout,  # type: ignore[attr-defined]
                launcher.command[:4],  # type: ignore[attr-defined]
                seen["interval"],
            )
            == (pinned, ["/opt/uv", "run", "--project", str(pinned)], 5.0)
        )


def test_run_launcher_delegates() -> None:
    calls: list[dict[str, object]] = []

    class Launcher:
        def run(self, **kwargs: object) -> None:
            calls.append(kwargs)

    stop = threading.Event()
    command.run_launcher(launcher=Launcher(), stop=stop, interval=1.0)  # type: ignore[arg-type]

    assert calls == [{"stop": stop, "interval": 1.0}]


class TestUnitDev:
    def test_refuses_without_a_pin(self, config_home: Path) -> None:
        result = CliRunner().invoke(cli, ["supervisor", "unit", "--dev"])

        assert result.exit_code == 1

    @pytest.mark.parametrize(
        ("which", "uv"), [("/opt/bin/uv", "/opt/bin/uv"), (None, "uv")], ids=["found", "missing"]
    )
    def test_prints_a_restart_always_unit(
        self,
        pinned: Path,
        monkeypatch: pytest.MonkeyPatch,
        which: str | None,
        uv: str,
    ) -> None:
        monkeypatch.setattr(command.shutil, "which", lambda name: which)

        output = CliRunner().invoke(cli, ["supervisor", "unit", "--dev"]).output

        assert (
            f"supervisor serve --dev --uv {uv}" in output,
            "Restart=always" in output,
            str(pinned) in output,
        ) == (True, True, True)


class TestDevCommands:
    def test_pin_reports_the_checkout(self, config_home: Path, checkout: Path) -> None:
        result = CliRunner().invoke(
            cli, ["supervisor", "dev", "pin", "--checkout", str(checkout), "--port", "9301"]
        )

        assert result.output.strip() == f"Dev supervisor page: {checkout} on port 9301"

    def test_pin_rejects_a_foreign_dir(self, config_home: Path, tmp_path: Path) -> None:
        result = CliRunner().invoke(cli, ["supervisor", "dev", "pin", "--checkout", str(tmp_path)])

        assert (result.exit_code, "pyproject" in result.output) == (1, True)

    def test_status_when_pinned(self, pinned: Path) -> None:
        output = CliRunner().invoke(cli, ["supervisor", "dev", "status"]).output

        assert (
            f"{pinned} on port 8766" in output,
            "supervisor/dev" in output,
            "no token yet" in output,
        ) == (True, True, True)

    def test_status_prints_the_page_url_once_started(self, pinned: Path) -> None:
        command.write_token(
            token="dev-tok", path=paths.page_token_path(instance=paths.Instance.DEV)
        )

        output = CliRunner().invoke(cli, ["supervisor", "dev", "status"]).output

        assert "Open: http://127.0.0.1:8766/?token=dev-tok" in output

    @pytest.mark.parametrize(
        "args",
        [["dev", "status"], ["serve", "--dev"], ["unit", "--dev"]],
        ids=["status", "serve", "unit"],
    )
    def test_unusable_pin_says_why(self, config_home: Path, args: list[str]) -> None:
        config_home.mkdir(parents=True)
        (config_home / "overwatch.yaml").write_text("dev: [unclosed\n", encoding="utf-8")

        result = CliRunner().invoke(cli, ["supervisor", *args])

        assert (
            result.exit_code,
            "unusable" in result.output,
            "not valid YAML" in result.output,
        ) == (
            1,
            True,
            True,
        )

    def test_status_when_not_pinned(self, config_home: Path) -> None:
        output = CliRunner().invoke(cli, ["supervisor", "dev", "status"]).output

        assert output.strip() == "No dev checkout is pinned."

    def test_unpin_when_pinned(self, pinned: Path) -> None:
        output = CliRunner().invoke(cli, ["supervisor", "dev", "unpin"]).output

        assert output.strip() == "Dev checkout unpinned."

    def test_unpin_when_not_pinned(self, config_home: Path) -> None:
        output = CliRunner().invoke(cli, ["supervisor", "dev", "unpin"]).output

        assert output.strip() == "No dev checkout was pinned."

    def test_rotate_token_drops_the_saved_token(self, config_home: Path) -> None:
        saved = paths.page_token_path(instance=paths.Instance.DEV)
        command.write_token(token="old", path=saved)

        CliRunner().invoke(cli, ["supervisor", "dev", "rotate-token"])

        assert saved.exists() is False
