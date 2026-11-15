# Finding Output Format

All Phase 3 agents MUST output findings in this exact structure.
The orchestrator parses these blocks for deduplication, merging,
and milestone grouping in Phase 4.

## Single Finding Block

```markdown
## Finding: <short descriptive title>
- **Location**: <file_path:line_number>
- **Pattern**: <pattern name from catalog, or "N/A">
- **Current**: <1-2 sentences describing what exists now>
- **Issue**: <1-2 sentences describing the problem or gap>
- **Recommendation**: <specific, actionable change>
- **Impact**: HIGH | MEDIUM | LOW
- **Effort**: S | M | L | XL
```

## Impact Classification

| Level | Criteria |
|-------|----------|
| HIGH | Correctness risk, data integrity, security, or blocks other improvements |
| MEDIUM | Maintainability, testability, or developer experience |
| LOW | Cosmetic, naming, or minor inconsistency |

## Effort Classification

| Level | Criteria |
|-------|----------|
| S | < 1 hour, single file, no migration |
| M | 1-4 hours, 2-5 files, no breaking changes |
| L | 1-2 days, cross-module, may need migration |
| XL | 3+ days, architectural change, needs ADR |

## Summary Section

Each agent ends with:

```markdown
## Summary
- Total findings: N
- HIGH impact: N (S: N, M: N, L: N, XL: N)
- MEDIUM impact: N (S: N, M: N, L: N, XL: N)
- LOW impact: N (S: N, M: N, L: N, XL: N)
- Key themes: <2-3 recurring themes>
```

## Milestone Grouping Hints

Agents should suggest milestone grouping in their summary:

```markdown
## Suggested Milestones
1. <milestone name> — findings 1, 3, 7 (theme: <theme>)
2. <milestone name> — findings 2, 5 (theme: <theme>)
```

The orchestrator uses these hints but may regroup during
Phase 4 synthesis.
