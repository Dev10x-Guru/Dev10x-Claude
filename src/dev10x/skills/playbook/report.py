"""Render a ``PlaybookDiff`` as markdown for CLI output (GH-192)."""

from __future__ import annotations

from dev10x.skills.playbook.compare import (
    MISSING,
    FieldDiff,
    PlaybookDiff,
    PlayDiff,
    StepDiff,
)

_MISSING_REPR = "<not set>"


def _format_field_value(value: object) -> str:
    """Render a field value for display, eliding long prompts."""
    if isinstance(value, str):
        compact = " ".join(value.split())
        if len(compact) > 80:
            return f"{compact[:77]}..."
        return compact
    return repr(value)


def _render_field_diff(diff: FieldDiff) -> str:
    default_repr = _format_field_value(diff.default_value)
    user_repr = (
        _MISSING_REPR if diff.user_value is MISSING else _format_field_value(diff.user_value)
    )
    return f"  - `{diff.field_name}`: default=`{default_repr}` user=`{user_repr}`"


def _render_step(step_diff: StepDiff) -> list[str]:
    symbol = {
        "new": "+",
        "removed": "-",
        "changed": "~",
        "unchanged": " ",
    }.get(step_diff.status, "?")
    header = f"{symbol} **{step_diff.subject}** _({step_diff.status})_"
    lines = [header]
    if step_diff.customized_fields:
        joined = ", ".join(sorted(step_diff.customized_fields))
        lines.append(f"    customized (preserved): {joined}")
    for field_diff in step_diff.upstream_changed_fields:
        lines.append(_render_field_diff(field_diff))
    return lines


def _render_play(play: PlayDiff, *, kind: str) -> list[str]:
    heading = f"### {kind}: `{play.play_name}` — {play.status}"
    if play.status == "unchanged":
        return [heading, "  (no upstream changes detected)"]
    if play.status == "not-overridden":
        return [heading, "  (user has not overridden this — defaults apply)"]
    if play.status == "removed":
        return [heading, "  (no longer present in plugin default — orphan override)"]
    lines: list[str] = [heading]
    for step_diff in play.step_diffs:
        if step_diff.status == "unchanged":
            continue
        lines.extend(_render_step(step_diff))
    return lines


def render_markdown_report(diff: PlaybookDiff) -> str:
    """Render a ``PlaybookDiff`` as a human-readable markdown report."""
    lines: list[str] = []
    lines.append(f"## Playbook diff: `{diff.skill_key}`")
    lines.append("")
    lines.append(f"- user: `{diff.user_path}`")
    lines.append(f"- default: `{diff.default_path}`")
    if diff.default_version or diff.user_version:
        lines.append(f"- versions: default=`{diff.default_version}` user=`{diff.user_version}`")
    lines.append("")

    if not diff.has_findings:
        lines.append("**No upstream changes detected.** User customizations are up to date.")
        return "\n".join(lines) + "\n"

    overridden = [p for p in diff.play_diffs if p.status not in ("unchanged", "not-overridden")]
    if overridden:
        lines.append("### Plays with upstream changes")
        lines.append("")
        for play in overridden:
            lines.extend(_render_play(play, kind="Play"))
            lines.append("")

    fragments_with_changes = [
        f for f in diff.fragment_diffs if f.status not in ("unchanged", "not-overridden")
    ]
    if fragments_with_changes:
        lines.append("### Fragments with upstream changes")
        lines.append("")
        for fragment in fragments_with_changes:
            lines.extend(_render_play(fragment, kind="Fragment"))
            lines.append("")

    lines.append("### How to apply")
    lines.append("")
    lines.append(
        "Customized fields are listed under each step and will **not** be"
        " overwritten. Run `/Dev10x:playbook edit <skill> <play>` to pull"
        " in upstream changes interactively, or edit the user YAML"
        " directly to add the new steps shown above."
    )
    return "\n".join(lines) + "\n"
