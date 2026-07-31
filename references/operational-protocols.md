# Operational Protocols: Documentation Patterns

Guidance for documenting field-evidence-backed operational procedures, including semantic clarifications and rationalization tables.

## Pattern Overview

Operational protocols (stall handling, incident recovery, error escalation) differ from standard documentation in that they depend on interpreting signals. This guide formalizes how to document such protocols to prevent misunderstanding and future incidents.

## Three-Part Structure

### 1. Semantic Clarification: What Signal Does NOT Prove

When a protocol depends on interpreting signals (heartbeat age, cost curves, status messages), explicitly state:

- **What the signal PROVES** — The concrete fact the signal establishes
- **What the signal does NOT prove** — The common false inference
- **Why the distinction matters** — The risk profile difference if misunderstood

**Example** (from stall-protocol.md):
> "A stale status-file mtime proves exactly one thing: the agent is not progressing. It does NOT prove the process is gone."

**Why it's critical**: Heartbeat silence could mean "process crashed" (needs respawn) or "process idle by design" (needs handshake first). The distinction determines whether you destroy a healthy overseer vs. recover a live agent.

### 2. Field Evidence: Concrete Case Studies

Back up semantic clarifications with field incidents — not hypotheticals.

**Structure per incident:**
1. Incident summary (what happened, when)
2. Key variable (handshake present/absent, flat spend, timestamp discipline)
3. Outcomes compared (side-by-side results when variable differed)
4. Documented conclusion (the variable that made the difference)

**Avoid:**
- Single incident (readers argue "that was edge case")
- Identical incidents (readers argue "coincidence")
- Narrative without the variable isolation (readers cannot replicate your reasoning)

**Example** (from stall-protocol.md):
> **crew-C0 incident**: Stalled 28min, spend flat. Assumed dead, respawned. Then 22min later posted duplicate comments — it woke up and had a conflict. 
> **crew-C2 incident**: Stalled 27min, spend flat, but performed handshake first. Responded to stand-down message, stayed silent in second window, clean takeover.
> **Variable that differed**: The handshake.
> **Conclusion**: Flat spend is not evidence of death. Responsiveness is what matters.

## Rationalization Table: Excuse vs Reality

A rationalization table documents false inferences your team might make, paired with field-backed reality.

**Purpose**: Turns retrospective incident analysis into proactive guardrails.

**Format**:

| Excuse | Reality |
|--------|---------|
| Common misunderstanding #1 | Field-backed counterpoint with concrete evidence |
| Common misunderstanding #2 | Why the excuse fails and what to check instead |

**Example entries** (from stall-protocol.md):
- **Excuse**: "Heartbeat is 28 min stale — it's dead"  
  **Reality**: Silence means not progressing, not dead. Perform the handshake first.

- **Excuse**: "Spend has been flat for 30 min, corroborates it's dead"  
  **Reality**: A cheap idle agent and a dead agent are indistinguishable on spend graphs. Flat cost is not evidence of death.

**Dual use**: The rationalization table serves both as a red-flag checklist (things to NOT assume) and a decision reference (what to check instead).

## When to Use This Pattern

Create an operational protocol document when:
- The procedure depends on interpreting signals or states
- Engineers might reasonably misinterpret a signal (false inference documented in rationalization table)
- The consequence of misunderstanding is operational (wrong response causes incidents)
- Field evidence exists or will accumulate during rollout

**Do NOT use for**: Simple step-by-step procedures, deployment checklists, or API documentation.

## Example: Full Operational Protocol Structure

```markdown
# Example Protocol

## What Signal X Does (and Does NOT) Prove

[Semantic clarification: state what the signal proves, what it doesn't,
and why the distinction matters.]

## Field Evidence

[Document 2+ incidents that isolate the key variable.]

### Incident A: [What happened]
[Summary, key variable state, outcomes]

### Incident B: [What happened]
[Summary, same context but key variable different, outcomes]

## Red Flags & Rationalization Table

| Excuse | Reality |
|--------|---------|
| [False assumption #1] | [Field-backed counterpoint] |
| [False assumption #2] | [Field-backed counterpoint] |

## Implementation Requirements

[Timestamp discipline, single-writer invariants, or other constraints
that enforcement of this protocol depends on.]
```

## Reviewer Checklist

When reviewing an operational protocol document:

1. ✓ Semantic clarification explicitly states what the signal does NOT prove
2. ✓ Field evidence includes 2+ incidents, each isolating one key variable
3. ✓ Incidents compare outcomes (not just stating "incident happened")
4. ✓ Rationalization table documents false inferences observed in the field
5. ✓ Each table entry pairs excuse with field-backed counterpoint (not generic advice)
6. ✓ Timestamp discipline and write-access constraints documented if protocol depends on them

## Related Patterns

- **Semantic Clarifications** also apply to signal-based rules in `.claude/rules/` and hook validation logic
- **Field Evidence** structure mirrors incident postmortems and RCA documentation
- **Rationalization Tables** prevent regression in future operational decisions
