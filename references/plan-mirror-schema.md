# plan.yaml Mirror Schema

The plan-sync hooks mirror the session task list into
`<git-toplevel>/.claude/session/plan.yaml`.
The Stop verdict and the task guard read it through the core reader
`dev10x.core.plan_mirror` (GH-1530, ADR-0034 Stage A0).
The writer stays in `dev10x.domain.documents.plan.Plan` until NS-15
moves it to the task-management plugin; the reader contract below
must not change when it does.

`tests/core/test_plan_mirror.py` pins this format.

## Top level

| Key | Type | Required | Meaning |
|-----|------|----------|---------|
| `plan` | mapping | no | Plan metadata (below). Absent on a plan with no metadata yet. |
| `tasks` | list of mappings | no | Mirrored tasks (below). Absent when no task was created. |

A missing file reads as an empty plan with no warning.
A file that fails to parse, or parses to something other than a
mapping, logs a warning naming the path and reads as empty.

## `plan` metadata

| Key | Type | Written by | Meaning |
|-----|------|------------|---------|
| `created_at` | ISO-8601 string | first task hook | When the plan was created, reset on a branch change |
| `branch` | string | task hooks, `branch` context write | Branch the plan belongs to |
| `status` | `in_progress` \| `completed` | task hooks | `completed` once every task is completed |
| `last_synced` | ISO-8601 string | every task hook | Freshness stamp used for foreign-plan detection |
| `completed_at` | ISO-8601 string | task hooks | When the last task completed |
| `archived_at` | ISO-8601 string | archive | Only on archived copies |
| `context` | mapping | `plan_sync_set_context` | Free-form keys; `work_on` / `routing_table` mark a guarded plan, `tickets` feeds session identity |

A non-mapping `plan` section is ignored with a warning.
A non-string `branch` or non-mapping `context` reads as absent.

## Task entries

| Key | Type | Required | Meaning |
|-----|------|----------|---------|
| `id` | string | yes | Harness task id (coerced to string) |
| `subject` | string | yes | Task title; a `Verify AC` subject marks the terminal task |
| `status` | `pending` \| `in_progress` \| `completed` | yes | Unknown values read as `pending` |
| `created_at` | ISO-8601 string | no | When the task was mirrored |
| `description` | string | no | Task description |
| `metadata` | mapping | no | Harness task metadata, e.g. `awaiting` |
| `started_at` | ISO-8601 string | no | Set on the move to `in_progress` |
| `completed_at` | ISO-8601 string | no | Set on the move to `completed` |

Deleted tasks are removed from the list rather than kept with a
`deleted` status.
Non-mapping list items are skipped.
Open tasks are those with status `pending` or `in_progress`.
