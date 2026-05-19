"""Platform registry core — catalog, config, and persisted user registrations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.domain.file_locks import atomic_write_text

REGISTRY_FILE = Dev10xConfigDir.platforms_yaml()


@dataclass(frozen=True)
class PlatformConfig:
    """Describes where a Dev10x target platform keeps its config and plugins."""

    name: str
    display_name: str
    config_dir: Path
    plugins_dir: Path
    settings_file: Path
    playbook_override: str | None = None

    def to_dict(self) -> dict:
        data = asdict(self)
        data["config_dir"] = str(self.config_dir)
        data["plugins_dir"] = str(self.plugins_dir)
        data["settings_file"] = str(self.settings_file)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> PlatformConfig:
        return cls(
            name=data["name"],
            display_name=data["display_name"],
            config_dir=Path(data["config_dir"]).expanduser(),
            plugins_dir=Path(data["plugins_dir"]).expanduser(),
            settings_file=Path(data["settings_file"]).expanduser(),
            playbook_override=data.get("playbook_override"),
        )


def _home_relative(*parts: str) -> Path:
    """Compose a path under the user home — resolved at call time, not import."""
    return Path.home().joinpath(*parts)


class PlatformCatalog:
    """Static, read-only catalog of supported target platforms.

    Encapsulates the built-in platform definitions and exposes a small
    query surface (``lookup`` / ``names`` / ``contains``) so callers do
    not poke at the raw dict.
    """

    def __init__(self, entries: dict[str, PlatformConfig] | None = None) -> None:
        self._entries = entries if entries is not None else _default_entries()

    def lookup(self, name: str) -> PlatformConfig:
        if name not in self._entries:
            raise KeyError(f"Unknown platform '{name}'. Known: {', '.join(self.names())}")
        return self._entries[name]

    def names(self) -> list[str]:
        return sorted(self._entries)

    def contains(self, name: str) -> bool:
        return name in self._entries

    def as_dict(self) -> dict[str, PlatformConfig]:
        return dict(self._entries)


def _default_entries() -> dict[str, PlatformConfig]:
    return {
        "claude-code": PlatformConfig(
            name="claude-code",
            display_name="Claude Code",
            config_dir=_home_relative(".claude"),
            plugins_dir=_home_relative(".claude", "plugins", "cache"),
            settings_file=_home_relative(".claude", "settings.json"),
        ),
        "copilot-cli": PlatformConfig(
            name="copilot-cli",
            display_name="GitHub Copilot CLI",
            config_dir=_home_relative(".copilot"),
            plugins_dir=_home_relative(".copilot", "plugins"),
            settings_file=_home_relative(".copilot", "config.yaml"),
        ),
        "windsurf": PlatformConfig(
            name="windsurf",
            display_name="Windsurf",
            config_dir=_home_relative(".windsurf"),
            plugins_dir=_home_relative(".windsurf", "plugins"),
            settings_file=_home_relative(".windsurf", "settings.json"),
        ),
        "continue": PlatformConfig(
            name="continue",
            display_name="Continue",
            config_dir=_home_relative(".continue"),
            plugins_dir=_home_relative(".continue", "extensions"),
            settings_file=_home_relative(".continue", "config.json"),
        ),
        "cursor": PlatformConfig(
            name="cursor",
            display_name="Cursor",
            config_dir=_home_relative(".cursor"),
            plugins_dir=_home_relative(".cursor", "extensions"),
            settings_file=_home_relative(".cursor", "settings.json"),
        ),
    }


def known_platforms() -> dict[str, PlatformConfig]:
    """Backward-compatible accessor — returns the default catalog as a dict."""
    return PlatformCatalog().as_dict()


class Registry:
    """Persisted list of platforms the current user has registered."""

    def __init__(self, *, path: Path | None = None) -> None:
        self.path = path or REGISTRY_FILE

    def load(self) -> dict[str, PlatformConfig]:
        if not self.path.is_file():
            return {}
        data = yaml.safe_load(self.path.read_text()) or {}
        entries = data.get("platforms", [])
        return {entry["name"]: PlatformConfig.from_dict(entry) for entry in entries}

    def save(self, platforms: dict[str, PlatformConfig]) -> None:
        serialised = {"platforms": [platforms[name].to_dict() for name in sorted(platforms)]}
        atomic_write_text(self.path, yaml.safe_dump(serialised, sort_keys=False))

    def add(
        self,
        name: str,
        *,
        config_dir: Path | None = None,
        playbook_override: str | None = None,
        catalog: PlatformCatalog | None = None,
    ) -> PlatformConfig:
        catalog = catalog or PlatformCatalog()
        if not catalog.contains(name):
            raise ValueError(f"Unknown platform '{name}'. Known: {', '.join(catalog.names())}")
        base = catalog.lookup(name)
        if config_dir:
            base = PlatformConfig(
                name=base.name,
                display_name=base.display_name,
                config_dir=config_dir,
                plugins_dir=config_dir / base.plugins_dir.relative_to(base.config_dir),
                settings_file=config_dir / base.settings_file.relative_to(base.config_dir),
                playbook_override=playbook_override or base.playbook_override,
            )
        elif playbook_override:
            base = PlatformConfig(
                name=base.name,
                display_name=base.display_name,
                config_dir=base.config_dir,
                plugins_dir=base.plugins_dir,
                settings_file=base.settings_file,
                playbook_override=playbook_override,
            )

        registered = self.load()
        registered[name] = base
        self.save(registered)
        return base

    def remove(self, name: str) -> bool:
        registered = self.load()
        if name not in registered:
            return False
        del registered[name]
        self.save(registered)
        return True

    def list(self) -> list[PlatformConfig]:
        registered = self.load()
        return [registered[name] for name in sorted(registered)]


def registered_platforms(*, registry: Registry | None = None) -> list[PlatformConfig]:
    """Service function: combine catalog defaults with user registrations.

    Returns the list of platforms the user has actively registered. Use
    :class:`PlatformCatalog` directly for the static built-in list.
    """
    return (registry or Registry()).list()
