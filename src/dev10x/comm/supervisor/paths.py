from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from dev10x.domain.dev10x_paths import Dev10xConfigDir

DEFAULT_PORT = 8765
DEV_PORT = 8766
PORT_ENV_VAR = "DEV10X_SUPERVISOR_PORT"
TOKEN_HEADER = "X-Supervisor-Token"


class Instance(StrEnum):
    RELEASE = "release"
    DEV = "dev"


def default_port(*, instance: Instance) -> int:
    return DEV_PORT if instance is Instance.DEV else DEFAULT_PORT


def state_dir(*, instance: Instance = Instance.RELEASE) -> Path:
    root = Dev10xConfigDir.home() / "supervisor"
    return root if instance is Instance.RELEASE else root / instance.value


def token_path(*, instance: Instance = Instance.RELEASE) -> Path:
    return state_dir(instance=instance) / "token"


def page_token_path(*, instance: Instance = Instance.RELEASE) -> Path:
    return state_dir(instance=instance) / "page-token"


def decisions_path(*, instance: Instance = Instance.RELEASE) -> Path:
    return state_dir(instance=instance) / "decisions.json"


def settings_path(*, instance: Instance = Instance.RELEASE) -> Path:
    return state_dir(instance=instance) / "settings.json"


def actions_log_path(*, instance: Instance = Instance.RELEASE) -> Path:
    return state_dir(instance=instance) / "actions.jsonl"
