# Merge guidance when no watcher is armed

Applies to whoever runs the merge gate — the watchdog in the full
harness, or you directly in the collapsed variant. It is never a crew
worker.

The merge discipline in `instructions.md` Phase 2 assumes the full
night-shift harness (watcher relaying `BASE MOVED`). In the collapsed
/ in-session variant — no `dev10x foreman watch` armed — a
rebase→CI-pending→park cycle re-triggers CI on every rebase and can
ping-pong indefinitely.

When `pr_get` reports the PR green and `MERGEABLE`, and the diff
cannot conflict with what merged since (e.g. docs-only, disjoint
files), merge directly and let the rebase-merge strategy replay the
commit. Only fall back to a local rebase when `pr_get` reports
`CONFLICTING`.
