# Hook Implementation Patterns

Guidance for maintaining consistent implementations when hooks exist
in multiple languages (Python and shell).

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

### Adding a new SessionStart/Stop feature

1. Write the logic in `src/dev10x/hooks/session.py` with an
   optional `data: dict | None` parameter
2. Add a call to the feature inside
   `hooks/scripts/session-start.py` (or `session-stop.py`),
   wrapped with `@audit_hook`
3. Add a test in `tests/hooks/test_orchestrators.py` verifying
   the feature runs and the orchestrator exits cleanly

Do NOT create a new hook entry in `hooks/hooks.json` for a
SessionStart/Stop feature — always extend the orchestrator.

### Audit wrapper application

Every entry in `hooks/hooks.json` is prefixed with `audit-wrap`:

```
$CLAUDE_PLUGIN_ROOT/hooks/scripts/audit-wrap <name> <command-path>
```

This captures total wall-clock timing (including `uv run`
startup) and injects `DEV10X_HOOK_SPAN_ID` so body-phase records
from `@audit_hook` correlate with wrap-phase records.

## Profile Tiers (GH-413)

Bash command validators declare a profile tier so users can dial
hook strictness up or down per session.

### Tier Assignment

| Profile | Validators | When to use |
|---------|-----------|-------------|
| `minimal` | Safety-critical rules only (DX001–DX005) | Quick fixes, throwaway scripts |
| `standard` | Minimal + skill-redirect + prefix-friction | Default for day-to-day work |
| `strict` | Standard + opinionated rules (e.g., commit-jtbd) | Feature branches, shared repos |

Each validator declares `rule_id` (stable identifier like `DX001`)
and `profile` (one of the above tiers). Lower-tier rules run at all
higher tiers — `minimal` rules are always active.

### Rule IDs

| rule_id | Validator | Tier |
|---------|-----------|------|
| DX001 | safe-subshell | minimal |
| DX002 | command-substitution | minimal |
| DX003 | execution-safety | minimal |
| DX004 | sql-safety | minimal |
| DX005 | pr-base | minimal |
| DX006 | skill-redirect | standard |
| DX007 | prefix-friction | standard |
| DX008 | commit-jtbd | strict |
| DX009 | redundant-fetch | standard (experimental) |
| DX010 | bash-aggregation | standard |
| DX011 | pipeline-allow | standard |
| DX012 | safe-expansion | minimal |
| DX013 | mcp-prefix | standard |
| DX014 | sensitivity-target | standard |
| DX015 | spec-drift | standard (experimental) |
| DX016 | inline-linter | standard |

### DX014 Sensitivity Axis: `ask`, Not `deny` (GH-604)

DX014 classifies *what the target is* (SECRET / CREDENTIAL / PII /
INFRA) — the third PAP axis, orthogonal to tier and reversibility. A
read-only-but-sensitive probe (`nc -zv` to infra, `gh secret list`,
`.env` read) is genuinely worth a prompt but must not be hard-blocked:
a hard `deny` drops the user to a manual `!` shell. DX014 therefore
emits `HookAsk` (`permissionDecision: "ask"`, exit 0) so the user can
approve in-session.

Genuine destructive writes are still hard-denied — by the safety-tier
validators (DX001–DX005/DX012), which run **before** DX014 in the
chain and short-circuit on a `deny`. DX014 only ever sees commands the
safety axis already cleared, so its `ask` (and a blessed `allow`, below)
never overrides a real block.

**Sensitivity-exception catalog (Tier 2, synced).** A user-owned
`~/.config/Dev10x/sensitivity-exceptions.yaml` downgrades blessed probes
from `ask` to `allow` (or keeps an explicit `ask`). It lives in the
user config home, so it syncs across every worktree. Entries use a
hybrid target+shape model — an entry applies when *every* supplied
matcher matches:

```yaml
exceptions:
  - description: bastion port probe
    label: infra              # optional: only when every match is this label
    shape: '\bnc\b.*-[zv]+'   # optional: regex on the command string
    target: 'bastion\.example\.internal'  # optional: regex on the command
    effect: allow             # allow (default) | ask
```

At least one of `label`/`shape`/`target` is required; a matcher-less
entry is rejected at load. A `label`-scoped entry only applies when
*all* sensitivity matches share that label, so it cannot silently bless
a command that also trips a second, un-blessed label. First applicable
entry wins (catalog order). A missing/malformed catalog fails open to
the default `ask`. The validator exposes `with_exceptions()` (mirroring
`with_patterns()`) as the injection seam.

### Configuration

Set via environment variables in `.claude/settings.json` or shell:

```bash
# Select profile tier (default: standard)
export DEV10X_HOOK_PROFILE=minimal

# Disable specific rules by ID (comma-separated)
export DEV10X_HOOK_DISABLE=DX006,DX008

# Enable experimental validators
export DEV10X_HOOK_EXPERIMENTAL=1
```

### Adding an Experimental Validator

New validators that need real-world validation before becoming
active-by-default should ship as `experimental=True`. Users opt
in via `DEV10X_HOOK_EXPERIMENTAL=1`. Once the validator is proven
stable, flip the flag to `False` and bump the tier appropriately.

Register the tier by appending a `ValidatorSpec` to `_SPECS` in
`src/dev10x/validators/__init__.py` (the typed dataclass replaced the
old `_VALIDATOR_SPECS` 5-tuple — see
`dev10x.validators.registry.ValidatorSpec`):

```python
_SPECS: list[ValidatorSpec] = [
    ...
    ValidatorSpec(
        module_path="dev10x.validators.new_rule",
        class_name="NewRuleValidator",
        rule_id="DX009",
        profile=ProfileTier.STANDARD,
        experimental=True,
    ),
]
```

Each validator class declares the same `rule_id`/`profile`/
`experimental` metadata as `ValidatorBase` class attributes; the
registry asserts the two agree at registration time.

### Reviewer Expectations

When adding a new validator:

1. Pick a stable `rule_id` (next free `DXNNN`)
2. Choose the correct profile tier (default: `standard`)
3. Update the rule-ID table above
4. Add a unit test verifying `should_run` and `validate` behavior
5. Add an integration test covering profile filtering if the
   rule has non-trivial scope (optional)

## Reference

See `.claude/rules/hook-state-schema.md` for documenting state
schemas. See `.claude/rules/hook-input-patterns.md` for input
validation patterns.
