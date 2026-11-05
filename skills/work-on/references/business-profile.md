# Business Profile — Light UI-Change-to-PR Play (GH-1026)

A profile for people who make small UI or content changes and ship
them as a PR without a developer driving the session: a marketer
fixing copy, a designer adjusting a color, a support lead updating a
help page. It is a play over the unchanged shipping kernel, not a
separate plugin — the GH-913 analysis rejected a zero-local-code
package, and this audience needs the hooks and validators *more*
than a developer does, not less.

## What the play does

The `business-change` fragment in
[`playbook.d/coding.yaml`](playbook.d/coding.yaml) runs:

1. **Set up workspace** — `dev10x:ticket-branch`
2. **Describe the change** — one or two plain sentences, and a
   question back when the request is ambiguous
3. **Make the change** — copy, labels, styles, images, layout only
4. **Preview the change** — plain-language summary, the diff, and the
   project's own checks, before anything is committed
5. **Commit the change** — `dev10x:git-commit`
6. **Create PR** — `dev10x:gh-pr-create`, with its preview gate
7. **Monitor CI** — `dev10x:gh-pr-monitor`
8. **Respond to review comments** — `dev10x:gh-pr-respond`
9. **Verify acceptance criteria** — `dev10x:verify-acc-dod`

It deliberately leaves out what only a developer should drive: the
design epic, the self-review fan-out, history grooming
(`dev10x:git-groom`) and merging (`dev10x:gh-pr-merge`). The play's
deliverable is an open PR with green CI; a developer merges it.

## Adopting it in a repository

Phase 1 of `dev10x:work-on` never classifies a request as
`business`, so a repository opts in by pointing its `feature` and
`bugfix` plays at the fragment. Add a `projects[]` entry to the
global playbook override:

```yaml
# ~/.config/Dev10x/playbooks/work-on.yaml
projects:
  - match_repo: acme/marketing-site
    overrides:
      - play: feature
        persist: true
        steps:
          - fragment: business-change
      - play: bugfix
        persist: true
        steps:
          - fragment: business-change
```

`match_repo` takes the same `org/repo` globs as the other
`projects[]` entries (see
[`config-resolution.md`](../../../references/config-resolution.md)). Every
other repository keeps the full coding plays.

`dev10x:work-on` reads `projects[].overrides[].steps` for the first
entry whose `match_repo` fits and expands the fragment there, so the
next work-on plan in that repository lists the nine steps above.
To confirm the entry selects the repository before that, run
`dev10x playbook diff --skill work-on` from inside it: it reports
which `projects:` entry matched. It does not expand the fragment.

## What it does not change

- **Gate pacing.** The play states each step's behavior in its
  prompt; whether a gate asks or auto-advances is still decided by
  `resolve_gate` from the project's posture. A dedicated gate preset
  for this audience is deferred until the single-baseline model
  (FRIC-M1) settles — see GH-1026.
- **Guardrails.** Every PreToolUse hook and validator stays on.
- **The skills.** All nine steps call the same skills the coding
  plays use; nothing here forks them.
