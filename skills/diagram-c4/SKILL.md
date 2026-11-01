---
name: dev10x:diagram-c4
description: >
  Use when someone asks for an architecture diagram, a system context
  or container view, "what talks to what", a component breakdown of
  one service, or a deployment picture — for an ADR, README, design
  doc, or onboarding page.
  TRIGGER when: drawing system structure at C4 level 1-3, dynamic, or
  deployment.
  DO NOT TRIGGER when: drawing interactions over time (use
  dev10x:diagram-sequence), a business process across roles (use
  dev10x:diagram-bpmn), or the repo already models C4 in Structurizr
  DSL (edit its workspace.dsl instead).
user-invocable: true
invocation-name: dev10x:diagram-c4
allowed-tools:
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/diagram-c4/scripts/:*)
  - Write
  - Edit
  - Read
  - Glob
---

# dev10x:diagram-c4

**Announce:** "Using dev10x:diagram-c4 to draw the <level> view of <system>."

## Orchestration

This skill follows `references/task-orchestration.md` patterns.

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Draw C4 diagram", activeForm="Drawing C4 diagram")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

## Pick the level from the question being answered

| Question | Level | Include |
|----------|-------|---------|
| "Who uses it and what does it talk to?" | 1 Context | `<C4/C4_Context>` |
| "What is it made of / what runs?" | 2 Container | `<C4/C4_Container>` |
| "What is inside this one service?" | 3 Component | `<C4/C4_Component>` |
| "Walk me through scenario X" | Dynamic | `<C4/C4_Dynamic>` |
| "Where does it run?" | Deployment | `<C4/C4_Deployment>` |

One level per diagram. A request that spans levels gets one file per
level, each zooming into a box from the level above.

## Workflow

1. **Check for an existing model.** `Glob` for `**/workspace.dsl` and
   `**/*.puml` containing `C4_`. When the repo already keeps a
   Structurizr model, edit that model instead — a second, hand-drawn C4
   picture drifts from it within a release. On that path steps 2–6 do
   not apply: `Read` back the changed DSL block, run the repo's own
   export target when it documents one (e.g. `make images`), and name
   the views that changed in your reply.

**Steps 2–6 apply only when no Structurizr model exists.**

2. **List the elements before drawing.** Name each person, system,
   container, and store the way the codebase names it. Every
   container gets a technology. Every data store — database, YAML or
   JSON files, bucket, cache — is a `ContainerDb`; a queue is a
   `ContainerQueue`. Say in your reply which edges you inferred rather
   than read from the code.
3. **Write the source** beside the document it serves
   (`docs/architecture/<system>-<level>.puml`), using only macros from
   [`references/c4-plantuml.md`](references/c4-plantuml.md):
   - the one `!include <C4/...>` for the level, right after `@startuml`
   - `title` naming the system and level
   - every `Rel` labeled with a verb phrase, plus the protocol when known
   - `SHOW_LEGEND()` as the last line before `@enduml`
4. **Render and validate:**

   ```bash
   ${CLAUDE_PLUGIN_ROOT}/skills/diagram-c4/scripts/render.sh <source.puml> [--format png|svg]
   ```

   It rejects a network `!include`, a C4 macro with no C4 include, and
   a missing Graphviz before PlantUML runs, then syntax-checks with a
   line number. Fix and re-run until it prints `rendered:`.
5. **Look at the image.** `Read` the PNG. Check every box carries the
   right kind and technology, labels are not swallowed (a bare `~` is
   PlantUML's escape character — see the reference), and no arrow
   crosses the whole picture. Untangle with `LAYOUT_LEFT_RIGHT()` and
   `Rel_R` / `Lay_R` hints, then re-render.
6. **Deliver.** Commit the `.puml` beside the rendered image and link
   the image from the document.

Toolchain and troubleshooting:
[`references/diagrams/rendering.md`](../../references/diagrams/rendering.md).

## Common Mistakes

| Mistake | Consequence |
|---------|-------------|
| Mixing levels in one picture | Readers cannot tell a deployable unit from a module; the diagram answers no question cleanly |
| Container without a technology | The description shifts into the `[technology]` slot and reads as nonsense |
| Unlabeled `Rel` | Arrows show coupling but not why it exists — the main thing a reviewer needs |
| `!include https://...` | Render breaks offline and drifts from the jar's C4 version |
| No `SHOW_LEGEND()` | Color and shape carry meaning nobody outside the team can decode |
| A second C4 picture beside a Structurizr model | Two sources of truth; one is wrong within a release |
