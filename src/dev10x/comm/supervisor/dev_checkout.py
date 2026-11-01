"""The local Dev10x checkout that serves the dev supervisor page (GH-1765).

Stored under ``dev:`` in ``~/.config/Dev10x/overwatch.yaml``. It is a fact
about the machine, not about a project, so it does not live in the
project-keyed ``friction.yaml``; a systemd daemon has no cwd to match one.
No ``dev:`` key means no dev page and no change in behaviour.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

import yaml

from dev10x.comm.supervisor import paths
from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.domain.file_locks import locked_yaml_update

DEV_KEY = "dev"
PROJECT_NAME = "dev10x"


class DevCheckoutError(ValueError):
    pass


@dataclass(frozen=True)
class DevCheckout:
    checkout: Path
    port: int = paths.DEV_PORT


def read_dev_checkout(*, path: Path | None = None) -> DevCheckout | None:
    target = path or Dev10xConfigDir.overwatch_yaml()
    try:
        text = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise DevCheckoutError(f"{target} is unreadable: {exc}") from exc
    try:
        doc = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise DevCheckoutError(f"{target} is not valid YAML: {exc}") from exc
    if not isinstance(doc, dict):
        raise DevCheckoutError(f"{target} must hold a mapping")
    dev = doc.get(DEV_KEY)
    if dev is None:
        return None
    if not isinstance(dev, dict):
        raise DevCheckoutError(f"{target}: `{DEV_KEY}` must be a mapping")
    checkout = dev.get("checkout")
    if not isinstance(checkout, str) or not checkout:
        raise DevCheckoutError(f"{target}: `{DEV_KEY}.checkout` must be a path")
    try:
        return validate_dev_checkout(checkout=Path(checkout), port=dev.get("port", paths.DEV_PORT))
    except DevCheckoutError as exc:
        raise DevCheckoutError(f"{target}: {exc}") from exc


def load_dev_checkout(*, path: Path | None = None) -> DevCheckout | None:
    try:
        return read_dev_checkout(path=path)
    except DevCheckoutError:
        return None


def _project_name(*, checkout: Path) -> str:
    try:
        with (checkout / "pyproject.toml").open("rb") as handle:
            project = tomllib.load(handle).get("project")
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise DevCheckoutError(f"{checkout} has no readable pyproject.toml: {exc}") from exc
    name = project.get("name") if isinstance(project, dict) else None
    return name.lower() if isinstance(name, str) else ""


def validate_dev_checkout(*, checkout: Path, port: object) -> DevCheckout:
    if not checkout.is_absolute():
        raise DevCheckoutError(f"checkout must be an absolute path, got {checkout}")
    if not checkout.is_dir():
        raise DevCheckoutError(f"checkout {checkout} is not a directory")
    if _project_name(checkout=checkout) != PROJECT_NAME:
        raise DevCheckoutError(f"{checkout} is not a Dev10x checkout (pyproject name)")
    if not isinstance(port, int) or isinstance(port, bool) or not 0 < port < 65536:
        raise DevCheckoutError(f"port must be 1-65535, got {port}")
    if port == paths.DEFAULT_PORT:
        raise DevCheckoutError(f"port {port} belongs to the release supervisor page")
    return DevCheckout(checkout=checkout, port=port)


def pin_dev_checkout(*, checkout: Path, port: int, path: Path | None = None) -> DevCheckout:
    pinned = validate_dev_checkout(checkout=checkout, port=port)
    with locked_yaml_update(path or Dev10xConfigDir.overwatch_yaml()) as doc:
        doc[DEV_KEY] = {"checkout": str(pinned.checkout), "port": pinned.port}
    return pinned


def unpin_dev_checkout(*, path: Path | None = None) -> bool:
    target = path or Dev10xConfigDir.overwatch_yaml()
    if not target.exists():
        return False
    with locked_yaml_update(target) as doc:
        return doc.pop(DEV_KEY, None) is not None
