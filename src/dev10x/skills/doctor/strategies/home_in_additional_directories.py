"""Strategy: home-in-additional-directories (GH-1140).

`~/.claude` is deliberately absent from the catalog's registered
working directories, which is why a Bash read of
`~/.claude/settings.json` trips the harness's path-scope gate — and
why the resulting prompt offers, as its second option, to register
`~/.claude` as an additional working directory.

Accepting that option is a much larger grant than the read that
provoked it. Under `defaultMode: acceptEdits` with an empty project
`ask` floor, a registered `~/.claude` lets an agent *edit*
`~/.claude/settings.json` unprompted — the settings file that governs
every other permission decision. The same argument applies with more
force to `$HOME` itself.

`settings-file-read` in `command-skill-map.yaml` removes the prompt
that offers the option; this strategy catches the case where a
previous session already accepted it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from dev10x.skills.doctor.strategy import (
    Context,
    Finding,
    Remediation,
    Strategy,
)


def _overreaching_roots() -> tuple[Path, ...]:
    """Directories that must never be registered as working directories.

    `~/.claude/memory`, `~/.claude/plugins` and `~/.config/Dev10x` are
    the deliberately narrow grants the catalog does ship; only the
    parents that would subsume a settings file are reported here.
    """
    home = Path.home()
    return (home, home / ".claude")


@dataclass(frozen=True)
class OverreachingDirectoryRemediation:
    """Remediation payload for an over-broad additionalDirectories entry."""

    entry: str
    settings_path: str

    def to_remediation(self, *, finding: Finding) -> Remediation:
        return Remediation(
            kind="edit_settings",
            target=self.settings_path,
            action={
                "bucket": "additionalDirectories",
                "remove": self.entry,
                "reason": (
                    "Registering this directory grants write access to the "
                    "settings files that govern every other permission "
                    "decision. Replace it with the narrow grants the catalog "
                    "ships (~/.claude/memory, ~/.claude/plugins, "
                    "~/.config/Dev10x), and read settings files with the Read "
                    "tool or audit_analyze_permissions instead."
                ),
            },
        )


def _settings_paths_from_context(context: Context) -> list[Path]:
    paths = list(context.settings_paths)
    if not paths:
        home = Path.home()
        paths = [
            home / ".claude" / "settings.json",
            home / ".claude" / "settings.local.json",
        ]
    return paths


def _additional_directories(path: Path) -> list[str]:
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    permissions = data.get("permissions")
    if not isinstance(permissions, dict):
        return []
    entries = permissions.get("additionalDirectories")
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, str)]


def _normalized(entry: str) -> Path:
    return Path(entry.rstrip("/")).expanduser()


def detect(context: Context) -> list[Finding]:
    """Report `$HOME` or `~/.claude` registered as a working directory."""
    overreaching = _overreaching_roots()
    findings: list[Finding] = []
    for path in _settings_paths_from_context(context):
        for entry in _additional_directories(path):
            if _normalized(entry) in overreaching:
                findings.append(_finding(entry=entry, path=path))
    return findings


def _finding(*, entry: str, path: Path) -> Finding:
    return Finding(
        strategy_id="home-in-additional-directories",
        severity="critical",
        location=str(path),
        evidence=(
            f"``{entry}`` is registered in permissions.additionalDirectories — "
            "this puts the settings files that govern every other permission "
            "decision inside an agent's writable scope"
        ),
        proposed_fix=(
            "Remove the entry and keep the catalog's narrow grants "
            "(~/.claude/memory, ~/.claude/plugins, ~/.config/Dev10x). To read a "
            "settings file, use the Read tool or "
            "mcp__plugin_Dev10x_cli__audit_analyze_permissions — neither is "
            "subject to the Bash path-scope gate that prompted for this."
        ),
        data=OverreachingDirectoryRemediation(entry=entry, settings_path=str(path)),
    )


def remediate(finding: Finding) -> Remediation:
    """Propose removing the over-broad working-directory registration."""
    return finding.to_remediation()


STRATEGY = Strategy(
    id="home-in-additional-directories",
    description=(
        "Flag $HOME or ~/.claude registered in additionalDirectories. The "
        "path-scope prompt on a settings-file read offers exactly this as its "
        "second option, and accepting it grants unprompted edits to the "
        "settings files themselves (GH-1140)."
    ),
    detect=detect,
    remediate=remediate,
)
