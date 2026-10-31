from __future__ import annotations

from pathlib import Path

from dev10x.domain.dev10x_paths import Dev10xConfigDir

DEFAULT_PORT = 8765
PORT_ENV_VAR = "DEV10X_SUPERVISOR_PORT"
TOKEN_HEADER = "X-Supervisor-Token"


def state_dir() -> Path:
    return Dev10xConfigDir.home() / "supervisor"


def token_path() -> Path:
    return state_dir() / "token"


def decisions_path() -> Path:
    return state_dir() / "decisions.json"


def actions_log_path() -> Path:
    return state_dir() / "actions.jsonl"
