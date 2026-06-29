# Display Conventions

Hybrid rendering convention for skill output that mixes nested
and flat structures (GH-730).

## Two shapes, two renderings

Skill output falls into two display shapes. Each has one
canonical rendering so output reads consistently across skills.

### Nested (phases → subtasks) → box-drawing tree

When output has more than two levels — a phase that owns
subtasks, an epic that owns children — render it as a
box-drawing tree. The glyphs make the parent/child structure
legible at a glance, which a flat numbered list cannot.

```
Phase 4: Execute feature
├─ 4.1  Set up workspace            → Dev10x:ticket-branch
├─ 4.2  Design implementation approach
│        ├─ Read relevant code
│        └─ Propose approach
├─ 4.3  Implement changes
└─ 4.4  Verify acceptance criteria  → Dev10x:verify-acc-dod
```

Glyph rules:

- `├─` — every node except the last at a given depth
- `└─` — the last node at a given depth
- `│` — continues the parent's vertical run across a nested
  block (align it under the parent's `├─`)
- Indent each nesting level by the width of the parent glyph so
  children line up beneath their parent's label

### Flat (two levels) → bullet-indent

When output is at most two levels deep — a heading and its
bullets — keep the bullet-indent form. A tree adds noise here
without adding structure. The work-on **Session mode summary**
is the canonical example:

```
Session mode summary
  Friction level: adaptive (auto-select recommended at all gates)
  Active modes:
    - solo-maintainer
      • Plan-approval gate bypassed
      • Shipping pipeline runs unattended
```

## Where this applies

- `Dev10x:work-on` Supervisor Approval Gate — the "Proposed
  plan" block renders as a box-drawing tree (phases →
  subtasks); the Session mode summary stays bullet-indent.
- Any skill presenting a multi-level plan, task tree, or
  hierarchy for supervisor review.

## Not a logic change

The tree is **presentation only**. Rendering a plan as a tree
does not change how it feeds `TaskCreate`, nor the
plan-approval gate's options or auto-approve rules. A skill may
switch a flat list to a tree (or back) without touching its
orchestration contract.
