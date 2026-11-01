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
`mcp__plugin_dev10x_cli__preset_pin_status` and verify with a
`resolve_gate` probe.

**If a policy already covers this checkout** (`gate_preset` /
`gate_overlays` resolved), honor it verbatim and **skip the gate** — a
persisted choice is the supervisor's answer, and re-asking is exactly
the friction this harness exists to remove. Record which policy was
adopted in `DECISIONS.md` and continue to 0.4.

## Step 3 — composing the policy

Invoke `Skill(dev10x:afk)` to compose the chosen policy — it is
read-before-write, so it is a no-op when the durable config already
matches. For `guided + afk`, set `gate_preset: guided` and let the
`afk` overlay ride on top — see `../../references/friction-levels.md`
and the `dev10x:afk` § Relationship to Presets and Overlays.

## `human_review` outranks the preset on the merge gate (GH-1056)

A composed `adaptive + [solo-maintainer, afk]` does **not** buy
auto-advancing merges on its own. `resolve_gate(gate="merge")` applies
a `human_review` floor, and floors are deny-overrides — no preset,
overlay, or session override lifts one. The flag defaults to `true`, so
an unconfigured repo asks:

```
effect: "ask"
reason: floor:human_review overrides preset:adaptive — humans review
        this repo — set human_review: false in the matching projects[]
        entry of ~/.config/Dev10x/friction.yaml if none do
```

**This is by design, not a bug.** `human_review` is a durable *project*
fact — whether humans are in the review loop on this repo — while
presets and overlays describe how *this session* was launched
(ADR-0019). A session flag lifting a project safety fact would let any
run declare its own oversight away.

The consequence for a night shift is sharp: Phase 0.3's copy promises
"full walk-away, merges included", and that promise holds only once
`human_review: false` sits in the matching `projects[]` entry. Without
it the run's first MERGE REQUEST freezes on an `AskUserQuestion` nobody
is awake to answer. Field case: a run configured `gate_preset: adaptive`
with both overlays and no `gate_overrides` did exactly that.

So resolve it here, in Phase 0.3, while the supervisor is present —
and prove it in Phase 0.4 with the merge-gate dry-run
([`preflight-checklist.md`](preflight-checklist.md) item 8). Setting
`human_review: false` is a real decision about the repo, not a
formality: it also makes `dev10x:verify-acc-dod` skip its
unresolved-threads and review-requested checks. If humans genuinely do
review this repo, the honest composition is `guided + afk` with merges
held for morning.

## The composed policy reaches a spawned worktree (GH-962 F1, GH-978)

A worker dispatched with `isolation="worktree"` gets a fresh checkout
with no session policy, on an agent-generated path that matches no
`projects[].match` glob. Before GH-978 that made
`resolve_gate(gate="merge")` fall back to defaults and return a
phantom `ask` even under `adaptive + afk`.

GH-978 is merged to `develop` (`fbc6a349`): `gate_query.py` probes the
worktree toplevel first and falls back to the git common dir that
`pin_gate_preset` keys the pin by, so a pinned repo policy reaches a
linked agent worktree. A merge `ask` a worker reports now reflects the
policy, so treat it as one. Do not hand-write config into a worker's
worktree to change it — pin the repo policy in Phase 0.3 instead.

## Never YOLO

This harness is **never YOLO**: do not offer, suggest, or accept
`bypassPermissions` / auto-mode as the answer to prompt risk. Walk-away
autonomy comes from the gate policy, which keeps the permission model
authoritative; auto-mode discards it.
