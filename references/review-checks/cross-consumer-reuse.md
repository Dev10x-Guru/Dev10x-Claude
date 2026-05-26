# Cross-Consumer Behavioural Reuse (GH-290)

Catches PRs that reuse an existing data structure (DB relation,
table, foreign key) for a new purpose when a sibling repository
(typically a frontend app) treats row presence as an implicit
feature flag for an unrelated feature. Populating the relation
to enable feature **B** silently activates feature **A** for
every affected tenant.

Parameter Change Analysis, Dead Code Detection, and the
Architecture Checklist (see `review-checks-common.md`) evaluate
impact from the **current** repository's call graph. None catch
coupling where row existence elsewhere gates feature visibility.

## When the check fires

Trigger only when the diff touches a model relation the PR did
**not** introduce — i.e., the diff dereferences an existing
`related_name`, ForeignKey, or OneToOne accessor on a model
with no sibling `migrations/*.py` diff in the same PR. Any of
the following detection signals qualifies:

- PR reads/writes via a `related_name` (or framework-equivalent
  reverse accessor) on a model with no migration diff in the PR
- PR adds a resolver, serializer, or handler that dereferences
  an existing relation
- PR adds a server-side admin form, inline, or service that
  populates an existing relation
- PR's body or linked ticket describes "reusing" or "extending"
  an existing relation for a new purpose

Skip for docs-only, config-only, pure test-only PRs, and PRs
that introduce the model/migration themselves (new relation,
no consumer coupling yet possible).

## How to run the check

1. **Load sibling-repo config** from
   `.claude/Dev10x/sibling-repos.yaml`. If the file is absent
   or has no entries, log "no sibling repos configured —
   skipping cross-consumer check" and return. Graceful no-op.

   Schema:
   ```yaml
   # .claude/Dev10x/sibling-repos.yaml
   repos:
     - path: /work/example/example-frontend
       kind: frontend
     - path: /work/example/example-mobile
       kind: mobile
   ```

2. **Extract the reused relation name** from the diff. Look
   for `<model>.<related_name>`, `<model>.<fk_field>`, or
   the model field referenced in resolver/admin/service code.

3. **Grep each sibling repo path** for boolean-coercion or
   length checks on the relation name:
   - `!!<relation>`, `<relation> &&`, `<relation>?.`
   - `<relation>.length > 0`, `<relation>.<sub>.length > 0`
   - Conditional rendering (`{<relation> && <Component/>}`)
   - Availability gates (`isAvailable = !!<relation>`)

4. **Classify each match by consumer-site kind:**

   | Consumer site | Severity |
   |---------------|----------|
   | Side-menu / route guard / page-availability hook | CRITICAL |
   | Permission check, tenant feature gate | CRITICAL |
   | Component visibility on a user-facing page | WARNING |
   | Debug panel, dev-only route, test fixture | INFO |
   | No matches found | (record as "no coupling detected") |

## Reporting

When the check fires with a match:
- Cite each consumer `file:line` in the review summary
- Quote the gating expression verbatim
- Recommend an explicit feature flag, permission, or admin
  toggle in the consumer rather than data-presence gating

## Degradation

- No `sibling-repos.yaml` → silent skip (do not error)
- Sibling repo path missing on disk → log + skip that entry
- `grep` returns no matches → record "no consumer coupling
  detected" in the review summary; do not raise a finding
