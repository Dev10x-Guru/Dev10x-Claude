# The roster — one at-a-glance view of every delegated chunk

The run directory already records everything: `manifest.md` holds the
queue, one `status-<chunk>.md` per worker holds liveness, and
`DECISIONS.md` / `decisions-<chunk>.md` hold rationale. What it does
not hold is a single place that answers *"what has been handed out,
and where is each piece right now?"* — the reader reconstructs that by
opening every status file in turn and inferring state from prose
heartbeat lines (GH-976).

`roster.md` is that view: one markdown table, in the run directory,
covering every chunk in the queue.

## It is a derived rendering, not a source of truth

`manifest.md` (what was queued) and `decisions-foreman.md` /
`DECISIONS.md` (why anything changed) remain authoritative. The roster
is a convenience projection of those plus live tracker state. When it
disagrees with them, **they win and the roster is wrong** — repair the
roster, never "correct" the manifest to match it.

This matters at recovery time: a fresh foreman rebuilds the roster
from `manifest.md` + the decision logs + `issue_get`/`pr_get`, and
loses nothing by discarding the file it found. Nothing may be recorded
*only* in the roster.

## Owner

**The foreman owns `roster.md` exclusively** — same single-writer
discipline as a heartbeat file, for a different reason: two writers
race on a rewritten table, where they merely interleave on an
append-only log.

The watchdog **reads** the roster and never writes it. Merge outcomes
reach the foreman through the channels the watchdog already owns —
`merged-shas` and a numbered `DECISIONS.md` entry — and the foreman
reflects them into the roster at its next wake, when it verifies that
chunk's closure. A watchdog running the collapsed in-session variant
with no foreman spawned owns the roster by default, because it is then
the only agent managing a queue.

## Shape

```markdown
# Roster — run 2026-08-01.s95kDH1ejzuW

| Chunk | Issue(s) | State | PR | ADR | Worker | Last update |
|---|---|---|---|---|---|---|
| c1 | #941 | merged | #981 | 016 | — | 2026-08-01 23:04 UTC |
| c2 | #952, #953 | delivered | #985 | 017 | crew-c2 | 2026-08-02 00:31 UTC |
| c3 | #960 | spawned | — | 018 | crew-c3 | 2026-08-02 00:38 UTC |
| c4 | #967 | split | — | — | — | 2026-08-01 22:10 UTC → #986 |
| c5 | #970 | deferred | — | — | — | 2026-08-01 21:55 UTC |
| c6 | #976 | queued | — | — | — | — |
```

- **Chunk** — the id used in `manifest.md` and `status-<chunk>.md`.
- **Issue(s)** — every tracker issue the chunk is expected to close.
- **State** — one of the vocabulary below, nothing else.
- **PR** — number once opened; `—` before that.
- **ADR** — the ADR number reserved for this chunk, or `—` when the
  chunk records none. See § ADR numbers below.
- **Worker** — the live agent name, or `—` when no agent is running
  (queued, deferred, merged, or between a stand-down and a respawn).
- **Last update** — `date -u`, never composed by hand, same rule as a
  heartbeat line.

## ADR numbers

**The foreman assigns ADR numbers; workers never discover them.** A
worker picking "the next free number" reads `docs/adr/` on its own
branch plus whatever is on the base — and cannot see a number a
sibling chunk already claimed on an unmerged branch. Three collisions
happened this way in one run (GH-1214 finding 4), including a chunk
announcing "017 is free on main and both open branches" minutes after
another chunk had renamed itself to 017 locally. What a worker can
observe is a lower bound, never the next free slot.

So the counter is roster state, like the chunk id:

1. At dispatch, if the chunk may record an ADR, take the next number
   above the highest in the ADR column AND the highest on the base
   branch, write it into the chunk's row, and interpolate it into the
   brief as `{{adr_number}}`.
2. The number is reserved from the moment it is written down — not
   when the file lands, and not when the PR merges. A `split` or
   `deferred` chunk keeps its reservation until someone deliberately
   releases it; recycling a number is how the third collision happened.
3. A worker needing a second ADR reports and asks. Do not let it pick.

## State vocabulary

| State | Means |
|---|---|
| `queued` | In `manifest.md`, not yet handed out |
| `spawned` | A worker is live on it |
| `delivered` | PR open, ready, CI green — waiting on the merge gate |
| `merged` | Merge gate ran; issues closed |
| `deferred` | Held tonight — supervisor call, blocked, or moved to the queue end |
| `split` | Scope cut; remainder carries its own issue number (record it in the row) |

A chunk whose worker was stood down and not yet replaced stays
`spawned` with `Worker` set to `—`; the empty worker cell is what
distinguishes it, so the reader is not told a dead agent is live.

## When the foreman updates it

**Piggyback on the write points that already exist.** No new cadence,
no timer, no "refresh the roster every N minutes" — a roster with its
own schedule is one more thing that goes stale unnoticed. Update the
affected row in the same turn as the heartbeat or decision line the
transition already produces:

| Transition | Existing write | Roster edit |
|---|---|---|
| Chunk handed out | spawn + `status-foreman.md` heartbeat | `queued` → `spawned`, set Worker |
| Worker reports PR open and green | heartbeat / relay prep | `spawned` → `delivered`, set PR |
| `MERGE REQUEST` relayed to the watchdog | heartbeat | Last update only |
| Merge confirmed (`merged-shas` / `DECISIONS.md` entry) | closure verification (`issue_get`) | `delivered` → `merged`, clear Worker |
| Scope cut / split | `decisions-<chunk>.md` entry | → `split`, note the remainder issue |
| Chunk deferred or moved to queue end | `DECISIONS.md` entry | → `deferred` |
| Stand-down handshake retires a worker | `DECISIONS.md` entry | clear Worker, keep state |

The morning wrap-up reads the roster as the skeleton of the
delivered/cut table, then confirms every row against the tracker
before it goes in the report — the roster is a rendering, and a
rendering is not evidence.

## Anti-patterns

- Generating the roster from a script or a new CLI subcommand. It is
  maintained by an LLM agent at existing write points, on purpose:
  a generator needs its own allow rule, its own pre-flight proof, and
  becomes a second thing that can be out of date.
- Recording anything **only** in the roster — a cut rationale, a
  blocked-by note, a PR that never made it to a decision entry.
- The watchdog editing it directly instead of going through
  `merged-shas` / `DECISIONS.md`.
- Free-text states (`"almost done"`, `"CI running"`). The vocabulary
  is closed so the table can be skimmed rather than read.
- Treating a roster row as sufficient evidence at the merge gate. Live
  `pr_get` / `ci_check_status` still decide; the row is a memory.
