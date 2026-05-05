from __future__ import annotations

import importlib
from typing import Any

import click


class LazyGroup(click.Group):
    def __init__(
        self,
        *args: Any,
        lazy_subcommands: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._lazy_subcommands: dict[str, str] = lazy_subcommands or {}

    def list_commands(self, ctx: click.Context) -> list[str]:
        base = super().list_commands(ctx)
        lazy = sorted(self._lazy_subcommands.keys())
        return base + lazy

    def get_command(
        self,
        ctx: click.Context,
        cmd_name: str,
    ) -> click.BaseCommand | None:
        if cmd_name in self._lazy_subcommands:
            return self._load_lazy(cmd_name)
        return super().get_command(ctx, cmd_name)

    def _load_lazy(self, cmd_name: str) -> click.BaseCommand:
        import_path = self._lazy_subcommands[cmd_name]
        module_path, attr_name = import_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        return getattr(module, attr_name)  # type: ignore[no-any-return]


@click.group(
    cls=LazyGroup,
    lazy_subcommands={
        "github-app": "dev10x.commands.github_app.github_app",
        "hook": "dev10x.commands.hook.hook",
        "init": "dev10x.commands.init.init",
        "permission": "dev10x.commands.permission.permission",
        "platform": "dev10x.commands.platform.platform",
        "validate": "dev10x.commands.validate.validate",
        "skill": "dev10x.commands.skill.skill",
    },
)
@click.version_option(package_name="Dev10x")
def cli() -> None:
    pass
