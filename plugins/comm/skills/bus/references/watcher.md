# Watcher Details

Reference for `dev10x:bus` — non-gating detail moved out of
`SKILL.md` under its 200-line budget (GH-1624).

## Why `--once` under background Bash

A background `watch.py <name> --once` has no 30-minute cap and wakes
the session only when it exits — that is, when mail is there. No gap
check is needed between runs: mail that landed while no watcher ran
is still unread, and the next `--once` reports it.

## Alternative — `Monitor`

Arm `Monitor` with the no-flag `watch.py <name>`,
`timeout_ms: 1800000`, and re-arm on each expiry. `Monitor` caps the
wait at 30 minutes, and plain `watch.py` baselines `new/` at start. So
after every arm, run `watch.py <name> --once --polls 0` as a plain
foreground Bash call: it prints what was already unread and exits
without waiting. Never start `--once` without `--polls 0` beside a
`Monitor` — it would wait too, and report the next arrival a second
time. Arm first, check second; a message landing between the two may
show up in both, so skip a path already handled.

That gap is why `--once` became the default (GH-1613): a message
landing between a `Monitor` expiry and the re-arm was silently
swallowed by the start-up baseline.

## Inbound screening

Every watcher line is `<VERDICT> <path>`, decided in this order:

| Verdict | When | File ends in |
|---------|------|--------------|
| `REFUSED` | sender named by `--refuse` | `cur/` |
| `EXPIRED` | `Expires` header is in the past | `cur/` |
| `DUP` | same sender, subject and body as a message this run saw within two minutes | `cur/` |
| `HELD` | sender named by `--hold` | `new/` |
| `NEW` | anything else | `new/` |

Duplicate detection lives in one watcher process. A `--once` run sees
only its own batch, so a loop spread across several runs is caught by
`--refuse` / `--hold`, not by `DUP`. A message with no `From:` header
is never `DUP`.

`send.py` refuses a body over 100,000 characters; send a file path
instead. `--expires-in MIN` sets `Expires`, which only the bus can
write.

## Exit codes and wire format

All five scripts exit 2 when a mailbox name, header, or path is
rejected (names are letters and digits joined by single `.`, `-` or
`_`; a `done.py` path must sit under the bus root). `done.py` exits 1
when it skips a file that is not in `new/` — the pre-plugin script
always exited 0.

The wire format matches the pre-plugin
`~/.claude/tools/claude-bus-*.py` scripts, so sessions on either side
interoperate.
