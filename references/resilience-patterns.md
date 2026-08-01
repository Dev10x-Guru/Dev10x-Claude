# Resilience Patterns for Multi-Session Orchestration

Protocol for skills that spawn agents or maintain state across session
boundaries (work-on, fanout, skill-audit, adr-evaluate, foreman).

When a session dies (API limit hit, host loss, or user kill), what
artifacts survive and what must be re-derived. Synthesized from
GH-965 (3 session deaths in one run).

## The contract in one line

**Exactly two things survive a session death: commits pushed to origin,
and text posted in a GitHub issue comment.** Everything else — agent
transcripts, scratchpads, run directories — is session-scoped and is
gone without warning.

| Artifact | Survives turn end | Survives session death |
|----------|------------------|----------------------|
| Commits pushed to origin | yes | yes |
| GitHub issue/PR comments | yes | yes |
| Agent transcripts (`SendMessage` channel) | yes | **no** |
| Scratchpad files | no | no |
| Run directory manifest/queue | no | no |

## Rule 1 — durable-first, as work is produced

Anything that must outlive the session goes into a pushed branch or
issue comment **immediately**, not saved for wrap-up. Deaths give no
warning — "write it down when you're finishing" reliably loses the work
of everyone who does not get to finish.

**For orchestrators**: Instruct every spawned agent to post handover
state (PR URL, branch name, completion status) to an issue comment as
soon as the artifact exists, and to update it continuously as work
progresses. A resumed orchestrator can then re-derive what remains from
these comments instead of trusting inherited claims alone.

**Cost of ignoring**: A 55-file caller inventory lived only in the run
directory across three session deaths. It was lost and rescued only by
re-verification — expensive and fragile.

## Rule 2 — a resumed orchestrator re-derives state from origin

An inherited brief from a prior run is a **hypothesis, not a record**.
Its author could not see whether work landed: a worker reporting
"committed work on a branch" may have been killed between the commit
and the push. Nothing in the handover distinguishes the two.

Before acting on any inherited claim:
- Verify branch existence and SHA via `git branch -r` or `git ls-remote`
- Verify PR existence and state via `pr_get`
- Verify issue state via `issue_get`

**Field case**: A run asserted a chunk had "committed work on a branch."
`git branch -r` showed the branch **did not exist**. Acting on the brief
would have wasted an hour chasing a tree that was never pushed.

**Same discipline as the merge gate**: A worker's report is "a memory,
not a fact" — this rule lifts the same verification to the session
boundary.

## Rule 3 — transcripts die with the session

`SendMessage` to an agent's `agentId` returns **"No transcript found
for agent ID"** once the dispatching session has died, even though the
ID is well-formed and the agent's commits are intact on origin.

**Critical distinction**:

| Boundary | Resumable? |
|----------|-----------|
| An agent **ends its turn** (same session) | yes — `SendMessage` resumes with full context |
| The **session dies** (API limit, host loss, kill) | **no** — every transcript is discarded |

Both are called "resume", and they behave **completely differently**.

**Consequence for orchestrators**: Every agent a resumed orchestrator
needs must be **freshly spawned**. A resumption plan built around
messaging the previous run's crew is dead on arrival — discovered only
after the plan commits to it. Rebuild the work queue from open tracker
issues and pushed branches instead.

## Rule 4 — nested orchestrators cannot use named agent addressing

`Agent(..., name=...)` fails from inside an agent with **"teammates
cannot spawn teammates."** A subagent orchestrator (like foreman) is
itself an agent, so the entire named-agent addressing surface is
unavailable to it.

The only working channel is raw `agentId` from the spawn result,
addressed via `SendMessage(to=<agentId>)`. But raw `agentId` is the
*less* durable handle: names are documented as surviving an agent's
completion, while `agentId` evaporates at the session boundary per
Rule 3.

**Practical consequence**: `agentId` is the only push channel a
subagent orchestrator has, and **it does not cross a session boundary**.

## Checklist for a resumed orchestrator

1. **Re-derive every inherited claim from origin** (Rule 2).
   - Check git branch existence, PR state, issue status via MCP tools
   - Do not assume prior run's assertions are still valid

2. **Assume zero live agents; spawn fresh** (Rule 3).
   - Do not attempt `SendMessage` resume of prior run's agents
   - Rebuild the work queue from tracker issues and issue comments

3. **Rebuild work queue from durable artifacts** (Rules 1 & 2).
   - Scan open issues for agent handover comments (post-Rule-1)
   - Scan git branches for pushed work from prior run
   - Do not rely on run directory state — it may be lost

4. **Instruct every new agent to post handover state early** (Rule 1).
   - Require handover post to issue comment after each artifact (PR,
     commit, merge)
   - This becomes the durable record a resumed run can rely on

## Multi-skill applicability

This protocol applies to any multi-session orchestration:
- `Dev10x:work-on` — phases dispatch agents; session death mid-phase
  requires re-derive + respawn
- `Dev10x:fanout` — spawns independent swarms; session death orphans
  swarm agents
- `Dev10x:skill-audit` — dispatches finder and judge agents; death
  mid-wave requires resumption
- `Dev10x:adr-evaluate` — architect dispatch vulnerable to account
  session limits
- `Dev10x:foreman` — unattended orchestration; assumes all rules above

When updating a multi-session skill, verify:
1. Agents are instructed to post handover comments (Rule 1)
2. Resumed run re-derives state before acting (Rule 2)
3. Session boundary respawns agents fresh, not via resume (Rule 3)
4. Skill is not a subagent itself, or uses raw agentId (Rule 4)

## See also

- `references/orchestration/subagent-status-protocol.md` — agent
  status reporting and controller branching logic
- `skills/foreman/references/durability-envelope.md` — foreman-specific
  implementation details and field incident walkthrough
