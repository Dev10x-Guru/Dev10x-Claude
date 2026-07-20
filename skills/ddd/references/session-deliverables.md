# Workshop Session Deliverables

## Required Deliverables (every session)

### 1. Decision Log Entries (`decisions.md`)

Every choice made during the session gets an entry. Even "we decided
NOT to do X" is a decision worth recording — it prevents re-debating.

```markdown
## D-NNN: [Short title]

- **Date:** YYYY-MM-DD
- **Status:** Active
- **Workshop:** NNN

**Decision:** [One sentence: what was chosen]

**Alternatives considered:**
1. [Option A] — [why rejected]
2. [Option B] — [why rejected]

**Rationale:** [Why this choice, what trade-offs accepted]
```

To supersede a prior decision:
```markdown
## D-NNN: [New title]

- **Date:** YYYY-MM-DD
- **Status:** Active
- **Supersedes:** D-MMM
- **Workshop:** NNN

**Decision:** [What changed and why the prior decision no longer holds]
```
Then update D-MMM's status: `**Status:** Superseded by D-NNN`

### 2. Workshop Record (`workshops/NNN-topic.md`)

```markdown
# Workshop NNN: [Topic]

- **Date:** YYYY-MM-DD
- **Participants:** [names]
- **Brief:** [One paragraph — what question were we answering?]

## Key Findings

[Narrative of what was discovered, decided, and why.
This is the historical record — write it for someone
who wasn't in the room.]

## Decisions Made

- D-NNN: [title]
- D-MMM: [title]

## Model Changes

[Summary of what changed in model.md. If nothing changed, say so.]

## Open Questions

[Anything left unresolved for the next workshop.
These become the starting point for the next session.]

## Artifacts Produced

| File | Action |
|---|---|
| `docs/domain/model.md` | Updated / Created |
| `docs/domain/decisions.md` | 3 entries added |
| ... | ... |
```

## Conditional Deliverables

### 3. Updated `model.md` — when types, pipeline, or aggregates changed

Update in place. Don't preserve old versions in the file — git does that.
Add `[D-NNN]` references where decisions shaped the model.

### 4. Updated `calculator.md` — when formulas or golden tests changed

If a new calculation stage was added, document:
- Input/output types
- Formula
- Golden test values (minimum 2 test cases)

### 5. Updated `epics.md` — when tickets added, refined, or completed

New tickets follow this format:
```markdown
### PERT-NN: [Title]

**When** [situation], **[actor] wants to** [motivation], **so [beneficiary] can** [outcome].

**Scope:** [What this ticket covers]

**Size:** S / M / L / XL
**Deps:** PERT-XX, PERT-YY
**Decisions:** [D-NNN], [D-MMM]
```

Write ticket stories in the project language. If acceptance criteria use
BDD or Gherkin-derived keywords, use Cucumber's official language
reference and include `# language: <code>` in feature-file-style blocks:
https://cucumber.io/docs/gherkin/languages/

Completed tickets: change status to `[DONE]`, don't delete.

### 6. New scenario in `stress-tests.md` — when a stress test was run

Follow the scorecard format from `references/stress-test-protocol.md`.
Append as a new section — never modify or remove existing scenarios.

### 7. Updated `glossary.md` — when new terms introduced

```markdown
| **Term** | Definition | Code mapping |
```

Every new domain term gets an entry. Map it to its TypeScript type or
function name.

### 8. Claude CLI prompts in `docs/prompts/` — when feature area is scoped

When a feature area is ready for implementation, produce a reusable
prompt that Claude Code can execute. Follow the pattern of existing
prompts — each prompt starts by reading specific domain docs, then
gives step-by-step implementation instructions with file paths and
test expectations.
