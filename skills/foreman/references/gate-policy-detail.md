# Phase 0.3 gate policy — full detail (GH-944)

The rationale, durable-policy-check procedure, and worktree caveat
behind the Phase 0.3 gate in `instructions.md`.

## Why the default is `adaptive + afk`

An unattended run whose gates still fire freezes on the first one
until morning, so the harness's own posture must be the walk-away
posture, and the supervisor opts *out*, not in.

## Step 1 — check the durable policy source first

Check the global `~/.config/Dev10x/friction.yaml` (ADR-0018; the
per-repo `.claude/Dev10x/config.yaml` is retired and holds nothing
durable). Read the matching `projects[]` entry, or call
`mcp__plugin_Dev10x_cli__preset_pin_status` and verify with a
`resolve_gate` probe.

**If a policy already covers this checkout** (`gate_preset` /
`gate_overlays` resolved), honor it verbatim and **skip the gate** — a
persisted choice is the supervisor's answer, and re-asking is exactly
the friction this harness exists to remove. Record which policy was
adopted in `DECISIONS.md` and continue to 0.4.

## Step 3 — composing the policy

Invoke `Skill(Dev10x:afk)` to compose the chosen policy — it is
read-before-write, so it is a no-op when the durable config already
matches. For `guided + afk`, set `gate_preset: guided` and let the
`afk` overlay ride on top — see `../../references/friction-levels.md`
and the `Dev10x:afk` § Relationship to Presets and Overlays.

## The composed policy does not always reach a spawned worktree (GH-962 F1)

A worker dispatched with `isolation="worktree"` gets a fresh checkout
with no session policy, on an agent-generated path that matches no
`projects[].match` glob — so `resolve_gate(gate="merge")` falls back
to defaults and returns a phantom `ask` even under `adaptive + afk`.

**GH-978 has landed the code-level fix** (worktree-first probe with
repo-root fallback) on branch `janusz/GH-978/worktree-gate-policy`;
until it merges to `develop`, warn every worker at spawn that a
phantom merge `ask` is an artifact of its checkout and not a
supervisor decision, and record the standing authorization once in
`DECISIONS.md`. Do not hand-write config into a worker's worktree as a
substitute. Full wording and rationale:
`overseer-discipline.md` § The merge gate reads `ask` in fresh
worktrees.

## Never YOLO

This harness is **never YOLO**: do not offer, suggest, or accept
`bypassPermissions` / auto-mode as the answer to prompt risk. Walk-away
autonomy comes from the gate policy, which keeps the permission model
authoritative; auto-mode discards it.
