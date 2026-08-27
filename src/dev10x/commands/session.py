"""`dev10x session` — manage the project's session config.

The `seed` subcommand exists so a shell-only `post-checkout` git hook
can guarantee a new checkout is ready without invoking a Claude skill (a
git hook cannot). Since ADR-0018 durable prefs live in a single global
`~/.config/Dev10x/friction.yaml` (keyed by project dir-path globs), and
the ephemeral per-repo `session.yaml`/`config.yaml` are retired — nothing
under a repo's `.claude/` is written on the hot path, so Claude Code's
self-settings gate never fires (GH-812). So `seed` now only:

- ensures the global `friction.yaml` exists (a starter with a `defaults:`
  block; hand-authored thereafter), and
- ensures a self-ignoring `.gitignore` under `.claude/Dev10x/` so the
  MCP-written auto-advance doubt-sink stays out of `git status`.

Both writes are idempotent (`O_EXCL`): an existing file is left
untouched, so the hook may call `seed` unconditionally.
"""

from __future__ import annotations

import os
from pathlib import Path

import click

from dev10x.domain.common.result import ErrorResult
from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.domain.documents.session_yaml import (
    PIN_SCOPES,
    FrictionYamlDocument,
    set_playbook_modes,
    upsert_project_prefs,
)
from dev10x.session.preset_pin import PIN_OVERRIDE_VALUES

_OVERLAY_CHOICES = ("solo-maintainer", "afk")

#: Values a per-gate override may take. Conditional preset values
#: (``auto-advance-if-*``) are preset-internal and not user-selectable here.
#: Shared with the MCP pin path so both entry points accept the same set.
_GATE_OVERRIDE_VALUES = PIN_OVERRIDE_VALUES


def _parse_gate_overrides(pairs: tuple[str, ...]) -> dict[str, str]:
    """Parse + validate ``toggle=value`` CLI pairs into a gate-override mapping.

    Validates eagerly against the known gate names and override values so a
    typo (``marge=ask``, ``merge=atuo-advance``) fails fast at the CLI rather
    than corrupting the durable ``friction.yaml`` and surfacing later as an
    ``UnknownToggleError`` deep inside ``resolve_gate`` (code review GH-886).
    """
    from dev10x.domain.gate_policy import _ENUM_TOGGLES

    overrides: dict[str, str] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise click.BadParameter(f"expected toggle=value, got {pair!r}")
        if key not in _ENUM_TOGGLES:
            raise click.BadParameter(f"unknown gate {key!r}; known: {sorted(_ENUM_TOGGLES)}")
        if value not in _GATE_OVERRIDE_VALUES:
            allowed = list(_GATE_OVERRIDE_VALUES)
            raise click.BadParameter(
                f"invalid value {value!r} for {key!r}; expected one of {allowed}"
            )
        overrides[key] = value
    return overrides


def _create_if_absent(*, target: Path, content: str) -> bool:
    """Atomically create ``target`` with ``content``; return whether written.

    Idempotent via ``O_EXCL`` — a present file is preserved so the hook may
    copy config from the source worktree first and fall back to this seed
    only when the source had none.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return False
    try:
        os.write(fd, content.encode())
    finally:
        os.close(fd)
    return True


@click.group()
def session() -> None:
    """Manage the project's .claude/Dev10x/ session config."""


@session.command()
@click.option(
    "--path",
    "project_path",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Project root (defaults to the current directory).",
)
@click.option(
    "--friction-level",
    type=click.Choice(["strict", "guided", "adaptive"], case_sensitive=False),
    default=None,
    help="Friction level for a fresh global friction.yaml (defaults to "
    "guided). Ignored when friction.yaml already exists.",
)
def seed(*, project_path: Path | None, friction_level: str | None) -> None:
    """Ensure the global friction.yaml + the .claude/Dev10x/ .gitignore exist.

    Idempotent (``O_EXCL``): present files are preserved, so a post-checkout
    hook may call ``seed`` unconditionally. Since ADR-0018 durable prefs are
    global (``~/.config/Dev10x/friction.yaml``) and the per-repo
    ``session.yaml``/``config.yaml`` are retired, seed no longer writes
    anything durable under the repo's ``.claude/``.
    """
    project_root = (project_path or Path.cwd()).resolve()

    # 1. Ensure the global friction.yaml exists (starter defaults block).
    friction_path = Dev10xConfigDir.friction_yaml()
    if _create_if_absent(
        target=friction_path,
        content=FrictionYamlDocument.render_starter(
            friction_level=(friction_level or "guided").lower(),
        ),
    ):
        click.echo(f"seeded {friction_path}")
    else:
        click.echo(f"friction.yaml already present at {friction_path}")

    # 2. Self-ignoring .gitignore keeps the MCP-written auto-advance doubt-sink
    # (and any other runtime artifact) under .claude/Dev10x/ out of git status,
    # so the clean-tree gates in verify_pr_state, gh-pr-merge Check 5,
    # verify-acc-dod, and create_pr never trip on it. A single "*" ignores
    # everything in the directory including the .gitignore itself (GH-809).
    gitignore = project_root / ".claude" / "Dev10x" / ".gitignore"
    if _create_if_absent(target=gitignore, content="*\n"):
        click.echo(f"seeded {gitignore}")
    else:
        click.echo(f".gitignore already present at {gitignore}")


def _inheritance_probes(*, project_root: Path) -> list[str]:
    """Paths whose existing entry a ``set-friction`` write should inherit from.

    The worktree comes first (an entry already covering this exact directory
    stays authoritative), then the repo root — which is where the entry a
    worktree-scoped write would shadow actually lives, since ``*/<repo>``
    never matches a worktree directory named ``agent-<id>`` (GH-1068 F3).
    A non-git or wedged checkout degrades to the worktree probe alone.
    """
    from dev10x.session.preset_pin import resolve_repo_identity

    probes = [str(project_root)]
    identity_result = resolve_repo_identity(cwd=str(project_root))
    if isinstance(identity_result, ErrorResult):
        return probes
    root = identity_result.value["root"]
    if root and root not in probes:
        probes.append(root)
    return probes


@session.command("set-friction")
@click.option(
    "--path",
    "project_path",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Project root (defaults to the current directory).",
)
@click.option(
    "--preset",
    type=click.Choice(["strict", "guided", "adaptive"], case_sensitive=False),
    required=True,
    help="Gate preset for this project.",
)
@click.option(
    "--overlay",
    "overlays",
    type=click.Choice(_OVERLAY_CHOICES, case_sensitive=False),
    multiple=True,
    help="Overlay(s) layered on the preset (repeatable).",
)
@click.option(
    "--gate-override",
    "gate_overrides",
    multiple=True,
    metavar="TOGGLE=VALUE",
    help="Per-gate override (repeatable), e.g. --gate-override merge=ask.",
)
def set_friction(
    *,
    project_path: Path | None,
    preset: str,
    overlays: tuple[str, ...],
    gate_overrides: tuple[str, ...],
) -> None:
    """Write this project's gate preferences into the global friction.yaml.

    The gate axis of ``Dev10x:friction-setup``: upserts a ``projects[]`` entry
    keyed by the repo's dir-path globs. Only deviations are written — omit an
    axis to leave it on the preset. Idempotent: re-running replaces the entry.
    """
    project_root = (project_path or Path.cwd()).resolve()
    prefs: dict[str, object] = {"gate_preset": preset.lower()}
    if overlays:
        prefs["gate_overlays"] = [overlay.lower() for overlay in overlays]
    parsed_overrides = _parse_gate_overrides(gate_overrides)
    if parsed_overrides:
        prefs["gate_overrides"] = parsed_overrides
    written = upsert_project_prefs(
        toplevel=str(project_root),
        prefs=prefs,
        inherit_from=_inheritance_probes(project_root=project_root),
    )
    click.echo(f"wrote friction preferences for {project_root} to {written}")


@session.command("pin")
@click.argument(
    "preset", type=click.Choice(["strict", "guided", "adaptive"], case_sensitive=False)
)
@click.option(
    "--overlay",
    "overlays",
    type=click.Choice(_OVERLAY_CHOICES, case_sensitive=False),
    multiple=True,
    help="Overlay(s) layered on the preset (repeatable).",
)
@click.option(
    "--gate-override",
    "gate_overrides",
    multiple=True,
    metavar="TOGGLE=VALUE",
    help="Per-gate override (repeatable), e.g. --gate-override merge=ask.",
)
@click.option(
    "--scope",
    type=click.Choice(list(PIN_SCOPES), case_sensitive=False),
    default="repo",
    show_default=True,
    help="repo: this repo + all present/future worktrees. "
    "repo-only: the main checkout. dir: this directory only.",
)
@click.option("--cwd", default=None, help="Directory to resolve the repo from (default: CWD).")
def pin(
    *,
    preset: str,
    overlays: tuple[str, ...],
    gate_overrides: tuple[str, ...],
    scope: str,
    cwd: str | None,
) -> None:
    """Pin a Phase-0 preset choice for this REPO into the global friction.yaml.

    Unlike ``set-friction``, the entry is keyed off the repo stem resolved
    from the git common dir — so a preset chosen inside worktree ``<repo>-3``
    also covers ``<repo>`` and any ``<repo>-9`` created later (GH-855).
    Idempotent: an entry already covering this checkout is replaced in place.
    """
    from dev10x.session.preset_pin import pin_preset

    result = pin_preset(
        preset=preset.lower(),
        overlays=[overlay.lower() for overlay in overlays] or None,
        gate_overrides=_parse_gate_overrides(gate_overrides) or None,
        scope=scope.lower(),
        cwd=cwd,
    )
    if isinstance(result, ErrorResult):
        raise click.ClickException(result.error)
    payload = result.value
    click.echo(f"pinned {preset.lower()} for {payload['repo_name']} to {payload['path']}")
    click.echo(f"match: {payload['match']}")


@session.command("set-playbook")
@click.option(
    "--skill",
    default="work-on",
    show_default=True,
    help="Playbook skill to configure (e.g. work-on).",
)
@click.option(
    "--mode",
    "modes",
    multiple=True,
    help="Active mode(s) to enable for this skill's playbook (repeatable).",
)
@click.option(
    "--skip-step",
    "skip_steps",
    multiple=True,
    metavar="SUBJECT",
    help="Play-step subject to always skip (repeatable), e.g. 'Draft Job Story'.",
)
def set_playbook(*, skill: str, modes: tuple[str, ...], skip_steps: tuple[str, ...]) -> None:
    """Write playbook active-modes / step skips into the global playbooks dir.

    The playbook axis of ``Dev10x:friction-setup``: records ``active_modes`` (and
    any per-step ``skip`` actions) into ``~/.config/Dev10x/playbooks/<skill>.yaml``,
    reusing the execution-modes resolver — no core plumbing change.
    """
    written = set_playbook_modes(
        skill=skill,
        active_modes=[mode for mode in modes],
        skip_steps=list(skip_steps) or None,
    )
    click.echo(f"wrote playbook modes for {skill} to {written}")
