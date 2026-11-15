# ADR Template

Use this template when creating new Architecture Decision Records.

---

# N. [Title - Short descriptive name]

Date: YYYY-MM-DD

## Status

Accepted

## Context

[Describe the situation that requires a decision]

### Current State
[What exists today]

### Problems
[What problems need solving - numbered list]

### Prerequisites
[Dependencies on other ADRs or systems]

## Decision

We will [brief summary of the decision].

### Architecture

![Component Architecture](diagrams/NNNN/component-architecture.png)

### Key Flows

#### Flow 1: [Name]
[Description]

![Flow Diagram](diagrams/NNNN/flow-name.png)

### New Components

| Component | Location | Responsibility |
|-----------|----------|----------------|
| `ComponentName` | `src/path/file.py` | [Single sentence] |

### Dependencies (Reused Components)

| Component | Location | How We Use It |
|-----------|----------|---------------|
| `ExistingComponent` | `src/path/file.py` | [How it's used] |

### Code Examples

```python
# src/path/file.py

@injectable_dataclass
class NewComponent:
    dependency: DependencyType

    def __call__(self, param: ParamType) -> ReturnType:
        pass
```

## Alternatives Considered

### Alternative 1: [Name]

[Description]

**Pros:**
- Pro 1
- Pro 2

**Cons:**
- Con 1
- Con 2

**Verdict:** Rejected - [Reason]

### Alternative N: [Selected Name]

[Description]

**Pros:**
- Pro 1
- Pro 2

**Cons:**
- Con 1
- Con 2

**Verdict:** Selected

## Consequences

### What Becomes Easier

1. [Benefit 1]
2. [Benefit 2]

### What Becomes More Difficult

1. [Challenge 1]
2. [Challenge 2]

### Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| [Risk 1] | Low/Medium/High | Low/Medium/High | [Mitigation] |

## Implementation Plan

### Phase 1: [Name]

**[System]:**
1. Step with file path
2. Step with file path

### Phase 2: [Name]

1. Step
2. Step

## References

### External Documentation

- [Link title](URL)

### Internal References

- [Related ADR](relative-link.md)
- [Linear ticket](https://linear.app/...)
- [Code reference](https://github.com/...)
