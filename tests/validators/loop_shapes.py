"""Canonical hand-rolled poll-loop shapes shared by the loop-rule tests.

These are the shapes `ci-loop-handrolled` and `watch-loop-handrolled`
exist to catch (GH-879, GH-1132, GH-1212). Three test modules assert
against them — the map's pattern tests, the validator's in-process
tests, and the dispatcher's end-to-end subprocess tests — and they are
only meaningful as long as all three test the SAME shape. Keeping one
copy here is what makes that true; three literals drift the moment one
is tweaked.
"""

from __future__ import annotations

# Names no CLI verb the fast-path token filter knows, so it also pins
# that a loop reaches the rule engine on its shape alone (GH-1212).
BARE_POLL_LOOP = """\
while true; do
  curl -sf https://x.test/ready && break
  sleep 30
done"""

UNTIL_POLL_LOOP = """\
until [ -f /tmp/ready ]; do
  echo waiting
  sleep 10
done"""

# The loop as field-reported on GH-1212: submitted through the Monitor
# tool, it reached the supervisor as a raw permission prompt.
PR_WATCH_LOOP = """\
prev=""
while true; do
  s=$(gh pr view 1234 --repo owner/repo --json state,mergedAt,reviewDecision \
2>/dev/null) || { sleep 300; continue; }
  cur=$(jq -r ".state" <<<"$s" 2>/dev/null) || cur=""
  if [ -n "$cur" ] && [ "$cur" != "$prev" ] && [ -n "$prev" ]; then echo "$cur"; fi
  [ -n "$cur" ] && prev="$cur"
  if jq -e '.state=="MERGED"' <<<"$s" >/dev/null 2>&1; then break; fi
  sleep 300
done"""
