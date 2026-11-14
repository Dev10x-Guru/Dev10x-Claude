"""Tests for `dev10x overwatch` (GH-1692)."""

from __future__ import annotations

import http.client
import json
import stat
import threading
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from click.testing import CliRunner, Result
from dev10x.domain.dev10x_paths import CONFIG_HOME_ENV_VAR, Dev10xConfigDir

from dev10x.cli import cli
from dev10x.comm.overwatch import paths
from dev10x.comm.overwatch.probes import Snapshot
from dev10x.commands import overwatch as command


@pytest.fixture
def config_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    home = tmp_path / "config"
    monkeypatch.setenv(CONFIG_HOME_ENV_VAR, str(home))
    Dev10xConfigDir.reset_cache()
    yield home
    Dev10xConfigDir.reset_cache()


@pytest.mark.parametrize(
    ("which", "uv"), [("/opt/bin/uv", "/opt/bin/uv"), (None, "uv")], ids=["found", "missing"]
)
def test_unit_prints_execstart(
    monkeypatch: pytest.MonkeyPatch, which: str | None, uv: str
) -> None:
    monkeypatch.setattr(command.shutil, "which", lambda name: which)

    result = CliRunner().invoke(cli, ["overwatch", "unit", "--port", "9000"])

    assert (
        f"overwatch serve --port 9000 --uv {uv}\n" in result.output,
        "Restart=always" in result.output,
        "[Install]" in result.output,
    ) == (True, True, True)


def test_there_is_no_dev_unit(config_home: Path) -> None:
    result = CliRunner().invoke(cli, ["overwatch", "unit", "--dev"])

    assert (result.exit_code, "No such option" in result.output) == (2, True)


def test_cli_lists_overwatch() -> None:
    assert "overwatch" in CliRunner().invoke(cli, ["--help"]).output


def test_write_token_mode_0600(tmp_path: Path) -> None:
    path = tmp_path / "overwatch" / "token"

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
        url = urlsplit(announced[0].removeprefix("Overwatch page: "))
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
        ["overwatch", "serve", "--port", "0", "--bus-root", str(tmp_path / "bus")],
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
        callable(seen["rearm"]),
    ) == (0, 0, True, True, True, True, True, True)


class FakeServer:
    server_address = ("127.0.0.1", 0)

    def __init__(self) -> None:
        self.stopped = threading.Event()
        self.closed = False

    def serve_forever(self) -> None:
        self.stopped.wait()

    def shutdown(self) -> None:
        self.stopped.set()

    def server_close(self) -> None:
        self.closed = True


def test_run_service_starts_rearm(
    config_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = command.build_app(
        kb_root=tmp_path / "kb", bus_root=tmp_path / "bus", relay_mailbox="relay", token="t"
    )
    server = FakeServer()
    monkeypatch.setattr(command, "make_server", lambda **kwargs: server)
    stop = threading.Event()
    rearmed = threading.Event()

    service = threading.Thread(
        daemon=True,
        target=command.run_service,
        kwargs={
            "app": app,
            "port": 0,
            "interval": 0.01,
            "stop": stop,
            "provider": lambda: Snapshot(sessions=[]),
            "announce": lambda line: None,
            "rearm": rearmed.set,
        },
    )
    service.start()
    try:
        fired = rearmed.wait(timeout=5)
    finally:
        stop.set()
        service.join(timeout=5)

    assert (fired, service.is_alive(), server.stopped.is_set(), server.closed) == (
        True,
        False,
        True,
        True,
    )


def test_build_rearm_disabled_by_empty_name(config_home: Path, tmp_path: Path) -> None:
    app = command.build_app(
        kb_root=tmp_path / "kb", bus_root=tmp_path / "bus", relay_mailbox="relay", token="t"
    )

    assert (
        command.build_rearm(app=app, agent_name="", interval=1.0, stop=threading.Event()) is None
    )


class FakeRelayRearm:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs

    def attempt(self) -> None:
        raise AssertionError("run_rearm is stubbed; attempt must not run")


@pytest.fixture
def fake_rearms(monkeypatch: pytest.MonkeyPatch) -> list[FakeRelayRearm]:
    instances: list[FakeRelayRearm] = []

    def build(**kwargs: object) -> FakeRelayRearm:
        instance = FakeRelayRearm(**kwargs)
        instances.append(instance)
        return instance

    monkeypatch.setattr(command, "RelayRearm", build)
    return instances


def test_build_rearm_wires_run_rearm_to_the_relay(
    config_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_rearms: list[FakeRelayRearm],
) -> None:
    app = command.build_app(
        kb_root=tmp_path / "kb", bus_root=tmp_path / "bus", relay_mailbox="relay", token="t"
    )
    stop = threading.Event()
    seen: dict[str, object] = {}
    monkeypatch.setattr(command, "run_rearm", lambda **kwargs: seen.update(kwargs))

    rearm = command.build_rearm(app=app, agent_name="relay", interval=2.0, stop=stop)
    assert rearm is not None
    rearm()
    (relay,) = fake_rearms

    assert (relay.kwargs, seen["attempt"], seen["interval"], seen["stop"]) == (
        {
            "bus_root": app.bus_root,
            "log_path": app.log_path,
            "relay_mailbox": "relay",
            "agent_name": "relay",
        },
        relay.attempt,
        2.0,
        stop,
    )


@pytest.mark.parametrize(
    "args",
    [["--relay-agent", ""], ["--instance", "dev"]],
    ids=["empty-agent-name", "dev-instance"],
)
def test_serve_without_rearm(
    config_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    args: list[str],
) -> None:
    seen: dict[str, object] = {}
    monkeypatch.setattr(command, "run_service", lambda **kwargs: seen.update(kwargs))
    monkeypatch.setattr(command.signal, "signal", lambda signum, handler: None)

    result = CliRunner().invoke(
        cli,
        ["overwatch", "serve", "--port", "0", "--bus-root", str(tmp_path / "bus"), *args],
    )

    assert (result.exit_code, seen["rearm"]) == (0, None)


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
        ["overwatch", "serve", "--no-rename", "--port", "0", "--bus-root", str(tmp_path / "bus")],
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

    CliRunner().invoke(cli, ["overwatch", "serve", "--bus-root", str(tmp_path / "bus")])

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
        ["overwatch", "serve", "--instance", "dev", "--bus-root", str(tmp_path / "bus")],
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
    result = CliRunner().invoke(cli, ["overwatch", "dev", "pin", "--checkout", str(checkout)])
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
                    "overwatch",
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


class FakeThread:
    def __init__(self) -> None:
        self.joined = False

    def join(self) -> None:
        self.joined = True


class TestServeWatchesTheDevPin:
    @pytest.fixture
    def watched(
        self,
        config_home: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> dict[str, object]:
        seen: dict[str, object] = {"thread": FakeThread()}

        def fake_start(**kwargs: object) -> FakeThread:
            seen["watch"] = kwargs
            return seen["thread"]  # type: ignore[return-value]

        monkeypatch.setattr(command, "start_dev_watcher", fake_start)
        monkeypatch.setattr(command.signal, "signal", lambda signum, handler: None)
        return seen

    def _serve(self, *, tmp_path: Path, args: list[str]) -> Result:
        return CliRunner().invoke(
            cli,
            ["overwatch", "serve", "--uv", "/opt/uv", "--bus-root", str(tmp_path / "bus"), *args],
        )

    def test_release_page_runs_the_watcher_on_its_stop(
        self,
        watched: dict[str, object],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(command, "run_service", lambda **kwargs: watched.update(kwargs))

        self._serve(tmp_path=tmp_path, args=[])
        watch = watched["watch"]

        assert (
            watch["stop"] is watched["stop"],  # type: ignore[index]
            watch["interval"],  # type: ignore[index]
            watched["stop"].is_set(),  # type: ignore[attr-defined]
            watched["thread"].joined,  # type: ignore[attr-defined]
        ) == (True, 5.0, True, True)

    def test_the_watcher_launches_the_pinned_checkout(
        self,
        watched: dict[str, object],
        pinned: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(command, "run_service", lambda **kwargs: None)

        self._serve(tmp_path=tmp_path, args=[])
        watcher = watched["watch"]["watcher"]  # type: ignore[index]
        launcher = watcher.make_launcher(watcher.read_pin())

        assert launcher.command[:4] == ["/opt/uv", "run", "--project", str(pinned)]

    def test_dev_page_never_runs_a_watcher(
        self,
        watched: dict[str, object],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        served: list[dict[str, object]] = []
        monkeypatch.setattr(command, "run_service", lambda **kwargs: served.append(kwargs))

        result = self._serve(tmp_path=tmp_path, args=["--instance", "dev", "--port", "0"])

        assert (result.exit_code, len(served), "watch" in watched) == (0, 1, False)

    def test_a_failing_service_still_stops_the_watcher(
        self,
        watched: dict[str, object],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def fail(**kwargs: object) -> None:
            watched.update(kwargs)
            raise OSError("port in use")

        monkeypatch.setattr(command, "run_service", fail)

        self._serve(tmp_path=tmp_path, args=[])

        assert (
            watched["stop"].is_set(),  # type: ignore[attr-defined]
            watched["thread"].joined,  # type: ignore[attr-defined]
        ) == (True, True)


def test_start_dev_watcher_runs_the_watcher_in_a_thread() -> None:
    calls: list[dict[str, object]] = []

    class Watcher:
        def run(self, **kwargs: object) -> None:
            calls.append(kwargs)

    stop = threading.Event()
    thread = command.start_dev_watcher(
        watcher=Watcher(),  # type: ignore[arg-type]
        stop=stop,
        interval=1.0,
    )
    thread.join(timeout=5)

    assert (calls, thread.daemon) == ([{"stop": stop, "interval": 1.0}], True)


class TestDevCommands:
    def test_pin_reports_the_checkout(self, config_home: Path, checkout: Path) -> None:
        result = CliRunner().invoke(
            cli, ["overwatch", "dev", "pin", "--checkout", str(checkout), "--port", "9301"]
        )

        assert result.output.strip() == (
            f"Dev Overwatch page: {checkout} on port 9301; {command.LIVE_NOTE}."
        )

    @pytest.mark.parametrize(
        "port", ["65536", "-1", "0"], ids=["just-past-max", "negative", "zero"]
    )
    def test_pin_rejects_a_bad_port(self, config_home: Path, checkout: Path, port: str) -> None:
        result = CliRunner().invoke(
            cli, ["overwatch", "dev", "pin", "--checkout", str(checkout), "--port", port]
        )

        assert (
            result.exit_code,
            "1-65535" in result.output,
            (config_home / "overwatch.yaml").exists(),
        ) == (
            1,
            True,
            False,
        )

    def test_pin_rejects_a_foreign_dir(self, config_home: Path, tmp_path: Path) -> None:
        result = CliRunner().invoke(cli, ["overwatch", "dev", "pin", "--checkout", str(tmp_path)])

        assert (result.exit_code, "pyproject" in result.output) == (1, True)

    def test_status_when_pinned(self, pinned: Path) -> None:
        output = CliRunner().invoke(cli, ["overwatch", "dev", "status"]).output

        assert (
            f"{pinned} on port 8766" in output,
            "overwatch/dev" in output,
            "no token yet" in output,
        ) == (True, True, True)

    def test_status_prints_the_page_url_once_started(self, pinned: Path) -> None:
        command.write_token(
            token="dev-tok", path=paths.page_token_path(instance=paths.Instance.DEV)
        )

        output = CliRunner().invoke(cli, ["overwatch", "dev", "status"]).output

        assert "Open: http://127.0.0.1:8766/?token=dev-tok" in output

    def test_unusable_pin_says_why(self, config_home: Path) -> None:
        config_home.mkdir(parents=True)
        (config_home / "overwatch.yaml").write_text("dev: [unclosed\n", encoding="utf-8")

        result = CliRunner().invoke(cli, ["overwatch", "dev", "status"])

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
        output = CliRunner().invoke(cli, ["overwatch", "dev", "status"]).output

        assert output.strip() == "No dev checkout is pinned."

    def test_unpin_when_pinned(self, pinned: Path) -> None:
        output = CliRunner().invoke(cli, ["overwatch", "dev", "unpin"]).output

        assert output.strip() == f"Dev checkout unpinned; {command.LIVE_NOTE}."

    def test_unpin_when_not_pinned(self, config_home: Path) -> None:
        output = CliRunner().invoke(cli, ["overwatch", "dev", "unpin"]).output

        assert output.strip() == "No dev checkout was pinned."

    def test_rotate_token_drops_the_saved_token(self, config_home: Path) -> None:
        saved = paths.page_token_path(instance=paths.Instance.DEV)
        command.write_token(token="old", path=saved)

        CliRunner().invoke(cli, ["overwatch", "dev", "rotate-token"])

        assert saved.exists() is False

    def test_rotate_token_says_when_the_new_one_arrives(self, config_home: Path) -> None:
        command.write_token(token="old", path=paths.page_token_path(instance=paths.Instance.DEV))

        result = CliRunner().invoke(cli, ["overwatch", "dev", "rotate-token"])

        assert (result.exit_code, result.output.strip()) == (
            0,
            "Dev page token dropped; the dev page issues a new one when it next starts "
            "(a new commit in the checkout, or `dev unpin` then `dev pin`).",
        )

    def test_rotate_token_without_a_saved_token(self, config_home: Path) -> None:
        result = CliRunner().invoke(cli, ["overwatch", "dev", "rotate-token"])

        assert (
            result.exit_code,
            paths.page_token_path(instance=paths.Instance.DEV).exists(),
            result.output.startswith("Dev page token dropped"),
        ) == (0, False, True)


ARTIFACT = {
    "id": "rollout",
    "title": "Rollout",
    "session": "dev10x-claude-75",
    "blocks": [{"id": "ship", "type": "button", "label": "Ship"}],
}


def _artifact_cli(*args: str, stdin: str | None = None) -> Result:
    return CliRunner().invoke(cli, ["overwatch", "artifact", *args], input=stdin)


class TestArtifactCommands:
    @pytest.fixture
    def written(self, config_home: Path) -> Result:
        return _artifact_cli("write", "--file", "-", stdin=json.dumps(ARTIFACT))

    def test_write_stores_the_document(self, written: Result) -> None:
        stored = json.loads(paths.artifacts_dir().joinpath("rollout.json").read_text())

        assert (
            written.exit_code,
            stored["revision"],
            "Artifact rollout revision 1 stored" in written.output,
            "http://127.0.0.1:8765/?token=<page token>#artifact/rollout" in written.output,
        ) == (0, 1, True, True)

    def test_write_to_the_dev_page(self, config_home: Path) -> None:
        result = _artifact_cli(
            "write", "--file", "-", "--instance", "dev", stdin=json.dumps(ARTIFACT)
        )

        assert (
            result.exit_code,
            paths.artifacts_dir(instance=paths.Instance.DEV).joinpath("rollout.json").is_file(),
            ":8766/" in result.output,
        ) == (0, True, True)

    def test_write_rejects_an_invalid_document(self, config_home: Path) -> None:
        result = _artifact_cli(
            "write", "--file", "-", stdin=json.dumps({**ARTIFACT, "blocks": [{"type": "html"}]})
        )

        assert (
            result.exit_code,
            "The artifact document is invalid" in result.output,
            paths.artifacts_dir().exists(),
        ) == (1, True, False)

    def test_list(self, written: Result) -> None:
        output = _artifact_cli("list").output

        assert output.startswith("rollout\tr1\t") and output.rstrip().endswith(
            "dev10x-claude-75\tRollout"
        )

    def test_list_when_empty(self, config_home: Path) -> None:
        assert _artifact_cli("list").output.strip() == "No artifacts are stored."

    def test_show(self, written: Result) -> None:
        shown = json.loads(_artifact_cli("show", "--id", "rollout").output)

        assert (shown["title"], shown["revision"]) == ("Rollout", 1)

    def test_show_unknown(self, config_home: Path) -> None:
        result = _artifact_cli("show", "--id", "missing")

        assert (result.exit_code, "No artifact 'missing'" in result.output) == (1, True)

    @pytest.mark.parametrize(
        ("artifact_id", "exit_code", "message"),
        [
            ("rollout", 0, "Artifact rollout removed."),
            ("missing", 0, "No such artifact."),
            ("../x", 1, "no such artifact"),
        ],
    )
    def test_remove(self, written: Result, artifact_id: str, exit_code: int, message: str) -> None:
        result = _artifact_cli("remove", "--id", artifact_id)

        assert (result.exit_code, message in result.output) == (exit_code, True)
