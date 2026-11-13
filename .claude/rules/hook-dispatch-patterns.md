---
paths:
  - "hooks/**"
  - "src/dev10x/hooks/**"
  - "src/dev10x/*/hooks/**"
  - "tests/hooks/**"
---

# Hook Dispatch Patterns

> **[OVERRIDE DETECTED]** — ~335 lines against the 200-line rule-file
> budget in `.claude/rules/INDEX.md` (GH-1438). Split out of
> `hook-patterns.md` under GH-1867, together with
> [`hook-validator-profiles.md`](hook-validator-profiles.md); its
> `paths:` front matter keeps it out of sessions that touch no hook code.
>
> **Cohesion justification.** Every section answers "how does a hook
> entry get wired and run here": cross-language parity (Python/shell),
> the direct-shebang + orchestrator dispatch pattern, the Stop-verdict
> merge rules, and the PostToolUse formatter's hunk-scope contract. A
> new Stop feature routinely needs both the orchestrator-consolidation
> rule and the verdict-merge rule, so they stay in one file.
>
> **Conditional split plan.** If this file passes ~400 lines, move
> § A Stop Feature May Carry a Verdict into `hook-stop-verdict.md` —
> it is the section that grows with each Stop feature. Do not split by
> language (Python vs shell): that cuts across the parity guidance
> every section needs.

Guidance for maintaining consistent implementations when hooks exist
in multiple languages (Python and shell).
Validator profiles, DX rule IDs and hook output envelopes live in
[`hook-validator-profiles.md`](hook-validator-profiles.md).

## When This Pattern Applies

When a PR adds a Python implementation of a hook that already exists
as a shell script (or vice versa), both implementations should be
functionally equivalent and use identical schemas.

Examples:
- `session_persist()` (Python) mirrors `session-stop-persist.sh`
- `session_goodbye()` (Python) mirrors `session-stop-goodbye.sh`

## Verification Checklist

### 1. Input/Output Schema Equivalence

- Both implementations read from identical stdin format (JSON)
- Both implementations write to identical stdout/file format
- Field names are identical across implementations
- Field types are compatible (JSON `true`/`false` vs shell
  `"true"`/`"false"`)

### 2. Error Handling Parity

- Both implementations handle missing stdin identically
- Both implementations handle malformed JSON identically
- Both implementations use same exit codes for error conditions
- Both implementations produce same error messages (or equivalent)

### 3. Fallback Value Consistency

- For optional fields, both implementations use identical defaults
- Missing/null values are handled the same way
- No silent failures due to different default handling

### 4. Data Type Representation

- Booleans: JSON `true`/`false` vs shell string `"true"`/`"false"`
  — aligned
- Integers: JSON `123` vs shell `"123"` — explicitly tested
- Lists: JSON array `[...]` vs shell multiline/CSV — conversion
  verified
- Timestamps: identical format (ISO8601, UTC, etc.)

### 5. Cross-Language Testing

- At least one test invokes shell implementation and parses output
- At least one test invokes Python implementation and parses output
- Both outputs are compared for schema equivalence
- Test covers at least one error condition with missing/null data

## Anti-Patterns

- Implementing Python version without testing against shell version
- Renaming fields during port (field name divergence)
- Different type representations (bool vs string) not caught by tests
- Different error handling (one throws, other returns null) — silent
  divergence
- Different fallback values in readers (one uses `""`, other uses
  `"unknown"`)

## Direct-Shebang + Orchestrator Pattern (GH-959)

**Default every new hook entry to a direct-shebang script wrapped
with `audit-wrap`.** Consolidate multi-entry events (SessionStart,
Stop) into a single orchestrator that runs features in-process.

### Anti-pattern: `uv run --project` entries

```json
"command": "uv run --project $CLAUDE_PLUGIN_ROOT dev10x hook session tmpdir"
```

Every invocation pays `uv` project-resolution, env-build, and the
full CLI import cost — even for trivial hooks. SessionStart fired
5 such entries on every session, multiplying the penalty.

### Correct pattern

```json
"command": "$CLAUDE_PLUGIN_ROOT/hooks/scripts/audit-wrap session-start $CLAUDE_PLUGIN_ROOT/hooks/scripts/session-start.py"
```

- `audit-wrap` records total_ms (including startup)
- The Python script uses a PEP 723 inline-metadata shebang
  (`#!/usr/bin/env -S uv run --script`)
- The orchestrator imports feature functions from
  `dev10x.hooks.*` and runs them in-process

### Consolidation checklist

When multiple feature functions share one event, create ONE
orchestrator script that:

1. Reads stdin **once**, parses the JSON into `data`
2. Passes `data` to each feature function (features accept an
   optional `data: dict | None` parameter; backward-compat stdin
   read when `None`)
3. Wraps each feature with `@audit_hook(name=..., event=...)`
   so body-phase timing lands in the JSONL log
4. Isolates failures — a raising feature must not skip the rest
   (catch `SystemExit` and `Exception` per feature)
5. For `additionalContext` producers (session_reload,
   session_guidance), extract a `build_*_context()` helper that
   returns the string; orchestrator merges all strings into one
   envelope
6. Preserves stdout when it matters (session_goodbye prints to
   the user); use `contextlib.redirect_stdout` in the orchestrator
   only for features that emit structured JSON

### A Stop Feature May Carry a Verdict (GH-1251)

The Stop orchestrator no longer discards return values. A feature may
return a verdict; the orchestrator merges them and emits **at most one**
envelope, mirroring what `SessionStart` does for `additionalContext`
(item 5 above).

Three constraints came out of building the first one:

1. **Ordering resolves the stdout collision.** `session_goodbye` prints
   to the user's terminal while a blocking decision must print JSON on
   stdout — the Stop orchestrator is the first to hold both kinds at
   once. Item 6 above prescribes `contextlib.redirect_stdout` for
   structured emitters; the resolution here is to capture the goodbye
   and **replay it only when nothing blocks**. A farewell printed while
   the turn is being continued asserts the session ended when it did
   not.
2. **A raising feature must not block.** `_verdict` returns `None` on
   any exception. A check that failed to run is not evidence that a
   gate was skipped, and the failure mode of guessing wrong here is a
   turn that cannot end.
3. **Two loop guards, not one.** A hook that always blocks needs
   `stop_hook_active` — but that is a documented harness contract this
   repo had never exercised, so it is paired with a
   cooldown marker keyed by session id. Either one alone suffices;
   together they survive the field being absent or renamed.

   **Retiring the marker needs evidence, and the evidence is now
   recorded (GH-1257).** The pair is meant to collapse to one once
   `stop_hook_active` is trusted, but nothing observed it: the audit
   log carried only wrap-phase timing, so "does a continuation arrive
   with the field set?" could not be answered from the field at all —
   and an unverifiable precondition is how belt-and-braces calcifies
   into permanent dead weight. `StopVerdict.signal` now names which
   branch ended the turn (`stop_hook_active`, `cooldown_marker`,
   `no_transcript`, `asked`, `blocked`) and `build_stop_verdict`
   attributes it to the audit record under `rule_id: stop-verdict`.
   Remove the marker when `stop_hook_active` appears there across a
   few harness versions — not before, and never merely because the
   guard looks redundant: what it prevents is a hook that re-blocks
   every turn forever.

   **Query `signal`, and group by `harness_version` (GH-1390).** Until
   GH-1390 neither key was written: the branch went into the generic
   `reason` slot `set_decision_attribution` gives every validator, so a
   reader following this paragraph queried `.signal` and got a zero —
   indistinguishable from the branch never firing, and a session acting
   on that reading nearly retired a guard a wider re-measurement found
   firing repeatedly. `reason` still carries the same value for
   back-compat; prefer `signal`. `harness_version` is read off the
   transcript the harness stamps it on, and is the literal `unknown`
   when unreadable — never absent, since an absent key re-creates the
   ambiguity this fixed. The marker goes only when all three agree:
   `stop_hook_active` present, `cooldown_marker` absent, across a few
   distinct `harness_version` values.

4. **Ask who is listening before blocking (GH-1314).** "A turn always
   ends on a widget" presumes a supervisor on the other end, and two
   cases have none. A **subagent** hands its report back to whoever
   dispatched it — one was observed echoing this module's own
   no-open-work steer as a status question, complying with a block it
   should never have received. There is no subagent branch: GH-1475
   captured that Stop is never invoked for a subagent (harness
   2.1.316), so the steer's text disposition is the only lever, and
   `SubagentStop` stays unregistered. Re-check with
   `DEV10X_STOP_PAYLOAD_KEYS=1` before adding a discriminator back.
   A session on **standby** has a
   supervisor who has explicitly said "stop asking until I speak";
   without that answer the widget's only replies re-arm it next turn,
   which is a gate with no exit rather than a gate.

   Standby is scoped by reading the turn's boundary user message, not
   a clock: a marker naming the same message means nothing has been
   said since, a different one means it has and the marker is dropped.
   That keeps it a pause rather than a disable, and keeps the lifetime
   free of a second writer. The branch carries its own
   `StopSignal` — a branch nobody can observe is a branch nobody can
   retire or trust, the same argument GH-1257 made for the other five.

5. **Open work never blocks.** GH-1377 blocked every turn that ended
   with actionable tasks ("the plan still has work on it"), on the
   theory that a Stop `block` is how auto-advance is implemented. The
   supervisor retired it as noise: auto-advance is owned by the skill
   and playbook instructions ("complete a task, start the next"), and
   a hook re-asserting them after each turn of a long plan added a
   block per turn and nothing else. Open work ends the turn under
   `open_work`. The task-list blocks fire only once the list says
   the work is done — a dirty tree, or the stand-down gate.

6. **A promise nothing kept blocks regardless of the list (GH-1829).**
   A turn whose closing paragraph declares an imminent action ("Now
   I'll run the tests") with no tool call after it ends under
   `promised_action`. It is checked after `stop_hook_active`, the
   cooldown marker, standby and an open widget, and before the task
   list, except when every open task is parked on subagents
   (GH-1464). The phrases live in
   `src/dev10x/core/hooks/stop_intent_patterns.yaml`, keyed by
   language. A broken `exempt` pattern disarms the gate, since losing
   an exemption would mean more blocks. An exemption covers only the
   sentence it sits in (GH-1854), so a conditional promise cannot
   excuse an unconditional one in the same paragraph. Inside the
   sentence the clause decides (GH-1894); clauses are cut at `,` `;`
   `:` and an em dash. A wait or a decision gate (`exempt`: "once you
   approve") excuses a promise from anywhere in the sentence, and so
   does a clause-opening "if/when/once/after you" `condition` that is
   not a preference and opens the sentence or a list item, up to the
   promise's own clause. A `preference` ("if you'd like") anywhere,
   or any other condition up to the promise's clause, excuses it only
   when the promise's own clauses carry no `immediate` marker (`now`,
   `right away`, `immediately`, `straight away`), comma or not. A
   condition never reaches back (GH-1869), so "let me know if you
   disagree, I'll run the tests now", "let me know if you'd like,
   I'll run the tests now" and "I'll run the tests, if you don't
   mind" all block.

**Keep the decision out of the hook.** `dev10x.core.hooks.stop_verdict`
holds the rule and is a pure function over `(payload, plan)`;
`build_stop_verdict` is the wiring that finds the plan and records the
marker. That split is what makes the rule testable without a
subprocess — the same separation `dev10x.core.hooks.format_scope` got under
GH-1143 — and it is why `decide` reads the marker but never writes it.

### Adding a new SessionStart/Stop feature

1. Write the logic in `src/dev10x/core/hooks/session.py` with an
   optional `data: dict | None` parameter
2. Add a call to the feature inside
   `hooks/scripts/session-start.py` (or `session-stop.py`),
   wrapped with `@audit_hook`
3. Add a test in `tests/hooks/test_orchestrators.py` verifying
   the feature runs and the orchestrator exits cleanly

Do NOT create a new hook entry in `hooks/hooks.json` for a
SessionStart/Stop feature — always extend the orchestrator.

### Hook files are split per plugin (GH-1556)

`hooks/hooks.json` holds the core entries; each other plugin's live
in `hooks/hooks.d/<plugin>.json`, listed under `"hooks"` in
`.claude-plugin/plugin.json` (ADR-0034). Matching hooks from all files
run in parallel, in no defined order — never rely on sequencing.

### Audit wrapper application

Every entry in every hook file is prefixed with `audit-wrap`:

```
$CLAUDE_PLUGIN_ROOT/hooks/scripts/audit-wrap <name> <command-path>
```

This captures total wall-clock timing (including `uv run`
startup) and injects `DEV10X_HOOK_SPAN_ID` so body-phase records
from `@audit_hook` correlate with wrap-phase records.

## A PostToolUse Formatter Stays Inside the Edit (GH-1143)

The `Edit|Write` formatter hook may reformat **only the lines the tool
call touched**, and may never apply lint fixes.

**Why.** The hook ran `ruff format` plus `ruff check --fix` over the
whole file after every edit. Each `Edit`+hook pair is evaluated in
isolation, with no memory of the sequence it belongs to — so a revert
that removed an import in one edit and restored its call site in another
had an *intermediate* state where the import genuinely was unused. F401
stripped it; nothing restored it; the file was left with a `NameError`
at a line nobody had edited. No individual step was wrong. The same pass
also collapsed `if/elif` into an unparenthesised mixed `and`/`or` in a
class the session never touched, and reflowed at 88 columns in a project
that configures 99 and passes its own pre-commit on the original forms.

**Rules for any new PostToolUse formatter:**

1. **Scope to the hunk.** Derive the edited line range from
   `tool_input` and pass it to the formatter (`ruff format --range`).
   Fall back to whole-file only when the range cannot be located, and
   retry whole-file when the tool rejects the range flag (older
   versions).
2. **Never prune imports or apply lint fixes.** Unused-import removal
   needs whole-file intent; a post-`Edit` pass sees one step of a
   possibly multi-step change. Leave it to the project's pre-commit.
3. **Honor the project's configuration.** Read `[tool.ruff]`, then
   `[tool.black] line-length`, then `max-line-length`. A project that
   runs its own pre-commit and configures no ruff formatter is left
   alone entirely — anything the hook rewrites there is net-new
   unreviewed change attributed to whoever commits next.
4. **Say what changed.** "PostToolUse hook modified `<file>` (likely a
   formatter)" does not distinguish reformatted whitespace from a
   deleted name the file still references. Emit a `systemMessage`
   naming the changed lines.

The decision logic lives in `dev10x.core.hooks.format_scope`, kept separate
from the hook so it is testable without a subprocess.

## Reference

See [`hook-validator-profiles.md`](hook-validator-profiles.md) for
validator profile tiers, the DX rule-ID table and hook output streams.
See `.claude/rules/hook-state-schema.md` for documenting state
schemas. See `.claude/rules/hook-input-patterns.md` for input
validation patterns.
