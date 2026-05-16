"""Compare a user playbook override against the plugin default (GH-192).

Surfaces upstream changes that the user may want to pull into their override
while preserving user customizations. Two playbook documents are compared:

- ``default`` — the plugin-shipped ``references/playbook.yaml``
- ``user``    — the user override at
                ``.claude/Dev10x/playbooks/<key>.yaml`` or
                ``~/.claude/memory/Dev10x/playbooks/<key>.yaml``

The diff distinguishes:

- **NEW** — a step or play present in the default but missing from the user
  override. Most often an upstream addition the user has not pulled in.
- **REMOVED** — a step or play in the user override that no longer exists
  in the default. Either the user intentionally pruned it, or upstream
  removed it.
- **CHANGED** — a step exists in both, but at least one inherited field
  has diverged. ``customized_fields`` lists keys the user has set to a
  value different from the default — those are preserved untouched.
  ``upstream_changed_fields`` lists keys the user did **not** override
  where the default value has changed.

The output is structured (dataclasses) so callers can render JSON, markdown,
or a CLI summary without re-parsing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Step fields the diff inspects. ``steps`` (epic children) and ``fragment``
# are handled separately because they recurse / are structural references.
COMPARED_FIELDS: tuple[str, ...] = (
    "type",
    "prompt",
    "skills",
    "agent",
    "model",
    "condition",
    "modes",
    "friction",
    "optional",
)

MISSING = object()


@dataclass(frozen=True)
class FieldDiff:
    """One field on one step whose default has changed."""

    field_name: str
    default_value: Any
    user_value: Any  # MISSING sentinel when the user did not set the field


@dataclass
class StepDiff:
    """Per-step diff entry."""

    subject: str
    status: str  # "new" | "removed" | "changed" | "unchanged"
    customized_fields: list[str] = field(default_factory=list)
    upstream_changed_fields: list[FieldDiff] = field(default_factory=list)


@dataclass
class PlayDiff:
    """Per-play diff entry."""

    play_name: str
    status: str  # "new" | "removed" | "changed" | "unchanged" | "not-overridden"
    step_diffs: list[StepDiff] = field(default_factory=list)
    prompt_changed: bool = False


@dataclass
class PlaybookDiff:
    """Top-level diff for one user playbook file vs the plugin default."""

    skill_key: str
    user_path: str
    default_path: str
    default_version: str | None
    user_version: str | None
    play_diffs: list[PlayDiff] = field(default_factory=list)
    fragment_diffs: list[PlayDiff] = field(default_factory=list)

    @property
    def has_findings(self) -> bool:
        return any(
            p.status not in ("unchanged", "not-overridden")
            for p in self.play_diffs + self.fragment_diffs
        )


def _step_key(step: dict[str, Any]) -> str:
    """Return the natural key for a step.

    Plain steps use ``subject``. Fragment references use ``fragment:<name>``
    so the diff can detect fragment-reference additions / removals without
    expanding the fragment inline.
    """
    fragment = step.get("fragment")
    if fragment:
        return f"fragment:{fragment}"
    subject = step.get("subject")
    if not subject:
        raise ValueError(f"Step missing subject and fragment: {step!r}")
    return str(subject)


def _index_steps(steps: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index steps by natural key. Later duplicates overwrite earlier ones."""
    return {_step_key(step): step for step in steps if isinstance(step, dict)}


def _diff_step(
    *,
    subject: str,
    default_step: dict[str, Any],
    user_step: dict[str, Any],
) -> StepDiff:
    """Diff one step that exists in both default and user playbooks."""
    customized: list[str] = []
    upstream_changed: list[FieldDiff] = []
    for key in COMPARED_FIELDS:
        default_value = default_step.get(key, MISSING)
        user_value = user_step.get(key, MISSING)
        if user_value is MISSING:
            if default_value is MISSING:
                continue
            upstream_changed.append(
                FieldDiff(
                    field_name=key,
                    default_value=default_value,
                    user_value=MISSING,
                )
            )
            continue
        if user_value != default_value:
            customized.append(key)
    status = "changed" if upstream_changed or customized else "unchanged"
    return StepDiff(
        subject=subject,
        status=status,
        customized_fields=customized,
        upstream_changed_fields=upstream_changed,
    )


def _diff_steps(
    *,
    default_steps: list[dict[str, Any]],
    user_steps: list[dict[str, Any]],
) -> list[StepDiff]:
    """Compare two step lists by natural key.

    Order is preserved using the default playbook as the canonical sequence:
    default steps first (in their order), then user-only steps appended.
    """
    default_index = _index_steps(default_steps)
    user_index = _index_steps(user_steps)
    diffs: list[StepDiff] = []
    for key, default_step in default_index.items():
        if key in user_index:
            diffs.append(
                _diff_step(
                    subject=key,
                    default_step=default_step,
                    user_step=user_index[key],
                )
            )
        else:
            diffs.append(StepDiff(subject=key, status="new"))
    for key in user_index:
        if key not in default_index:
            diffs.append(StepDiff(subject=key, status="removed"))
    return diffs


def _user_play_steps(
    *,
    play_name: str,
    user_doc: dict[str, Any],
) -> list[dict[str, Any]] | None:
    """Locate the user's override step list for a play, if any."""
    for override in user_doc.get("overrides") or []:
        if isinstance(override, dict) and override.get("play") == play_name:
            steps = override.get("steps")
            if isinstance(steps, list):
                return steps
    return None


def _diff_play(
    *,
    play_name: str,
    default_play: dict[str, Any],
    user_steps: list[dict[str, Any]] | None,
) -> PlayDiff:
    """Diff one play. ``user_steps=None`` means the user has not overridden it."""
    default_steps = default_play.get("steps") or []
    if user_steps is None:
        return PlayDiff(play_name=play_name, status="not-overridden")
    step_diffs = _diff_steps(default_steps=default_steps, user_steps=user_steps)
    has_changes = any(diff.status != "unchanged" for diff in step_diffs)
    status = "changed" if has_changes else "unchanged"
    return PlayDiff(play_name=play_name, status=status, step_diffs=step_diffs)


def _diff_fragments(
    *,
    default_fragments: dict[str, Any],
    user_fragments: dict[str, Any],
) -> list[PlayDiff]:
    """Diff fragment maps. Each fragment is treated as a tiny play."""
    diffs: list[PlayDiff] = []
    for name, default_steps in default_fragments.items():
        if not isinstance(default_steps, list):
            continue
        user_steps = user_fragments.get(name)
        if not isinstance(user_steps, list):
            diffs.append(PlayDiff(play_name=name, status="not-overridden"))
            continue
        step_diffs = _diff_steps(default_steps=default_steps, user_steps=user_steps)
        has_changes = any(d.status != "unchanged" for d in step_diffs)
        diffs.append(
            PlayDiff(
                play_name=name,
                status="changed" if has_changes else "unchanged",
                step_diffs=step_diffs,
            )
        )
    for name in user_fragments:
        if name not in default_fragments:
            diffs.append(PlayDiff(play_name=name, status="removed"))
    return diffs


def compare_playbooks(
    *,
    default_doc: dict[str, Any],
    user_doc: dict[str, Any],
    skill_key: str,
    user_path: str,
    default_path: str,
) -> PlaybookDiff:
    """Compare two parsed playbook documents.

    Both inputs are the result of ``yaml.safe_load``. ``default_doc`` is
    expected to follow the playbook schema (``defaults:`` map of plays);
    ``user_doc`` follows the override schema (``overrides:`` list of plays).
    Either may also define a top-level ``fragments:`` map.
    """
    defaults = default_doc.get("defaults") or {}
    default_fragments = default_doc.get("fragments") or {}
    user_fragments = user_doc.get("fragments") or {}

    play_diffs: list[PlayDiff] = []
    for play_name, default_play in defaults.items():
        if not isinstance(default_play, dict):
            continue
        user_steps = _user_play_steps(play_name=play_name, user_doc=user_doc)
        play_diffs.append(
            _diff_play(
                play_name=play_name,
                default_play=default_play,
                user_steps=user_steps,
            )
        )

    # Flag user overrides for plays that no longer exist upstream.
    default_play_names = set(defaults.keys())
    for override in user_doc.get("overrides") or []:
        if not isinstance(override, dict):
            continue
        play_name = override.get("play")
        if play_name and play_name not in default_play_names:
            play_diffs.append(PlayDiff(play_name=str(play_name), status="removed"))

    fragment_diffs = _diff_fragments(
        default_fragments=default_fragments,
        user_fragments=user_fragments,
    )

    return PlaybookDiff(
        skill_key=skill_key,
        user_path=user_path,
        default_path=default_path,
        default_version=default_doc.get("version"),
        user_version=user_doc.get("version"),
        play_diffs=play_diffs,
        fragment_diffs=fragment_diffs,
    )
