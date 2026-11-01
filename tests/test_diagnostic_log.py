"""Tests for dev10x.core.diagnostic_log (GH-1639)."""

from __future__ import annotations

import json
import logging
import os
import stat
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from dev10x.domain.log_redaction import REDACTED

import dev10x.mcp.server_cli as server_cli
from dev10x.commands.skill import skill
from dev10x.core.diagnostic_log import (
    DEFAULT_LOG_DIR,
    LOG_DIR_ENV,
    LOGGER_NAME,
    JsonlDiagnosticHandler,
    StderrFallbackHandler,
    configure_diagnostic_log,
    log_dir,
)


@pytest.fixture
def log_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv(LOG_DIR_ENV, str(tmp_path / "log"))
    return tmp_path / "log"


@pytest.fixture
def clean_logger() -> Iterator[logging.Logger]:
    logger = logging.getLogger(LOGGER_NAME)
    saved_handlers, saved_level = list(logger.handlers), logger.level
    logger.handlers = [
        h
        for h in logger.handlers
        if not isinstance(h, JsonlDiagnosticHandler | StderrFallbackHandler)
    ]
    yield logger
    logger.handlers, logger.level = saved_handlers, saved_level


@pytest.fixture
def records(log_root: Path, clean_logger: logging.Logger) -> list[dict[str, Any]]:
    configure_diagnostic_log(component="mcp")
    log = logging.getLogger(f"{LOGGER_NAME}.coding.github")
    log.info("fetched PR %s with GITHUB_TOKEN=abc", 7, extra={"pr_number": 7, "token": "t"})
    try:
        raise ValueError("boom")
    except ValueError:
        log.exception("call failed")
    [path] = list(log_root.glob("mcp-*.jsonl"))
    return [json.loads(line) for line in path.read_text().splitlines()]


@pytest.fixture
def configure_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(
        "dev10x.core.diagnostic_log.configure_diagnostic_log",
        lambda *, component: calls.append(component),
    )
    return calls


def test_skill_group_attaches_the_skill_sink(configure_calls: list[str]) -> None:
    skill.callback()

    assert configure_calls == ["skill"]


def test_mcp_main_attaches_the_mcp_sink(
    configure_calls: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("dev10x.mcp.wiring.select_transport_with_daemon_fallback", lambda: "stdio")
    monkeypatch.setattr(server_cli.server, "run", lambda *, transport: None)

    server_cli.main()

    assert configure_calls == ["mcp"]


def test_the_suite_never_writes_the_real_log_dir() -> None:
    assert log_dir() != Path(DEFAULT_LOG_DIR)


def test_log_dir_defaults_to_tmp_dev10x_log(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(LOG_DIR_ENV, raising=False)

    assert log_dir() == Path(DEFAULT_LOG_DIR)


def test_one_jsonl_line_per_record(records: list[dict[str, Any]]) -> None:
    assert [r["level"] for r in records] == ["INFO", "ERROR"]


def test_record_shares_the_audit_field_names(records: list[dict[str, Any]]) -> None:
    first = records[0]

    assert set(first) == {"ts", "level", "component", "logger", "message", "fields"}
    assert first["component"] == "mcp"
    assert first["logger"] == "dev10x.coding.github"


def test_message_and_fields_are_redacted(records: list[dict[str, Any]]) -> None:
    first = records[0]

    assert first["message"] == f"fetched PR 7 with GITHUB_TOKEN={REDACTED}"
    assert first["fields"] == {"pr_number": 7, "token": REDACTED}


def test_exception_records_carry_error_type(records: list[dict[str, Any]]) -> None:
    assert records[1]["error_type"] == "ValueError"


def test_configure_is_idempotent_per_component(
    log_root: Path, clean_logger: logging.Logger
) -> None:
    first = configure_diagnostic_log(component="skill")
    second = configure_diagnostic_log(component="skill")

    assert first is second
    assert [h for h in clean_logger.handlers if isinstance(h, JsonlDiagnosticHandler)] == [first]


def test_warnings_still_reach_stderr(
    log_root: Path, clean_logger: logging.Logger, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_diagnostic_log(component="skill")
    log = logging.getLogger(f"{LOGGER_NAME}.x")

    log.info("quiet detail")
    log.warning("loud problem")

    assert capsys.readouterr().err == "loud problem\n"


def test_stderr_fallback_is_attached_once(log_root: Path, clean_logger: logging.Logger) -> None:
    configure_diagnostic_log(component="mcp")
    configure_diagnostic_log(component="skill")

    fallbacks = [h for h in clean_logger.handlers if isinstance(h, StderrFallbackHandler)]
    assert len(fallbacks) == 1


def test_log_dir_is_private(records: list[dict[str, Any]], log_root: Path) -> None:
    assert stat.S_IMODE(log_root.stat().st_mode) == 0o700


def test_an_existing_wide_open_dir_of_ours_is_tightened(
    log_root: Path, clean_logger: logging.Logger
) -> None:
    log_root.mkdir(mode=0o755)
    log_root.chmod(0o755)
    configure_diagnostic_log(component="mcp")

    logging.getLogger(f"{LOGGER_NAME}.x").info("hello")

    assert stat.S_IMODE(log_root.stat().st_mode) == 0o700


def test_a_symlinked_log_dir_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean_logger: logging.Logger
) -> None:
    target = tmp_path / "elsewhere"
    target.mkdir()
    link = tmp_path / "log"
    link.symlink_to(target)
    monkeypatch.setenv(LOG_DIR_ENV, str(link))
    monkeypatch.setattr(logging, "raiseExceptions", False)
    configure_diagnostic_log(component="mcp")

    logging.getLogger(f"{LOGGER_NAME}.x").info("hello")

    assert list(target.iterdir()) == []


def test_a_refused_dir_reports_once_not_per_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean_logger: logging.Logger
) -> None:
    link = tmp_path / "log"
    link.symlink_to(tmp_path)
    monkeypatch.setenv(LOG_DIR_ENV, str(link))
    handler = configure_diagnostic_log(component="mcp")
    reported: list[logging.LogRecord] = []
    monkeypatch.setattr(handler, "handleError", reported.append)

    log = logging.getLogger(f"{LOGGER_NAME}.x")
    log.info("one")
    log.info("two")

    assert len(reported) == 1


def test_a_log_dir_owned_by_someone_else_is_refused(
    log_root: Path, monkeypatch: pytest.MonkeyPatch, clean_logger: logging.Logger
) -> None:
    log_root.mkdir(mode=0o700)
    monkeypatch.setattr(os, "getuid", lambda: os.stat(log_root).st_uid + 1)
    monkeypatch.setattr(logging, "raiseExceptions", False)
    configure_diagnostic_log(component="mcp")

    logging.getLogger(f"{LOGGER_NAME}.x").info("hello")

    assert list(log_root.iterdir()) == []


def test_a_write_failure_never_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean_logger: logging.Logger
) -> None:
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    monkeypatch.setenv(LOG_DIR_ENV, str(blocker))
    monkeypatch.setattr(logging, "raiseExceptions", False)
    configure_diagnostic_log(component="mcp")

    logging.getLogger(f"{LOGGER_NAME}.x").info("still fine")
