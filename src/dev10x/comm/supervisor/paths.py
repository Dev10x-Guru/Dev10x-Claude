from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True)
class InstanceProfile:
    default_port: int
    keeps_page_token: bool
    renames_sessions: bool


PROFILES = {
    Instance.RELEASE: InstanceProfile(
        default_port=DEFAULT_PORT, keeps_page_token=False, renames_sessions=True
    ),
    Instance.DEV: InstanceProfile(
        default_port=DEV_PORT, keeps_page_token=True, renames_sessions=False
    ),
}


def profile(*, instance: Instance) -> InstanceProfile:
    return PROFILES[instance]


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


def read_token(*, path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
