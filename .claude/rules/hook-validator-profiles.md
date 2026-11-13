---
paths:
  - "hooks/scripts/validate-*.py"
  - "src/dev10x/core/hooks/hook_transport.py"
  - "src/dev10x/core/validators/**"
  - "src/dev10x/validators/**"
  - "tests/hooks/test_hook_transport.py"
  - "tests/validators/**"
---

# Hook Validator Profiles

> **[OVERRIDE DETECTED]** — ~360 lines against the 200-line rule-file
> budget in `.claude/rules/INDEX.md` (GH-1438). Split out of
> `hook-patterns.md` under GH-1867, together with
> [`hook-dispatch-patterns.md`](hook-dispatch-patterns.md); its
> `paths:` front matter keeps it out of sessions that touch no
> validator code.
>
> **Cohesion justification.** Every section answers "how does a
> validator decide, and how does its decision reach Claude Code": the
> profile tiers, the DX rule-ID table, the per-rule design notes
> (DX014, DX017, DX020, DX006 live hints) and the output-stream
> contract. The per-rule notes lean on the tier table and on the
> deny > ask > allow precedence, so a reviewer checking one rule needs
> both.
>
> **Conditional split plan.** If this file passes ~400 lines, move the
> per-rule design notes (§ DX020, § DX014, § DX017, § Live Hints) into
> `hook-validator-rules.md`, leaving tiers, the rule-ID table, output
> streams, configuration and registration here. Do not split by
> language (Python vs shell) — that cuts across the parity guidance in
> `hook-dispatch-patterns.md` both halves need.

Hook wiring, the orchestrator pattern and the Stop-verdict rules live
in [`hook-dispatch-patterns.md`](hook-dispatch-patterns.md).

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
| DX017 | write-destination | standard |
| DX018 | exec-flag | standard |
| DX019 | review-stamp (MCP ship tools, own hook entry) | standard |
| DX020 | agent-brief (`Agent` calls, own hook entry) | standard |

### DX020 Reads the Brief, Not a Command (GH-1835)

A plain `Agent` call carries a free-form brief, and that is where a
subagent rebuilds a skill by hand or works around a hook denial. DX020
matches the brief against `agent-skill-map.yaml` and flags a match that
names neither the mapped skill nor an accepted alias. It runs from its
own `validate-agent-brief` entry, because the Bash chain exits on any
tool but `Bash` and `Monitor`.

1. **Advisory by default.** It returns a `HookHint`, so the dispatcher
   reads the finding before the subagent starts and the call proceeds.
   `dx020: {mode: deny}` in a project's `friction.yaml` entry turns it
   into a deny.
2. **Patterns name the action.** `git commit` and `open a PR` are in the
   map; the bare word `commit` is not, since nearly every brief has it.
   **Names match as whole tokens (GH-1874).** A name token is a run of
   word characters, `:`, `-`, `.` and `/`; trailing punctuation and a
   leading `:` or `-` are trimmed, so `foo__push_safe`,
   `src/push_safe.py` and `./push_safe` do not name `push_safe` while a
   sentence-final `push_safe.` does. An MCP tool counts under its full
   registered name, listed as its own alias. An alias with other
   characters, such as `Skill(test)`, must appear as written, ignoring
   case. A slash-joined list such as `push_safe/pr_ready` names
   neither, so DX020 over-reports it: the safe side of the trade.
3. **The escape is a line, not a flag.** `dev10x-ok: <reason>` in the
   brief skips the check and leaves the reason in the transcript. An
   empty reason does not count.
4. **Projects edit the map in `friction.yaml`.**
   `dx020.skill_keywords.add` appends entries and `.remove` drops
   default entries by skill name.

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

**The operand is classified, not just the shape (GH-1278).** A read is
an *effect* reachable by unbounded means — `cat`, `head`, `rg`, `jq`,
`awk`, `sed`, a redirect, a symlink, different quoting. GH-1260
established by controlled test that neither permission namespace can
close that: a `Read()` rule governs the Read tool only and says nothing
about a Bash command reading the same path, while a blanket
`Bash(rg:*)` allow makes every file on the machine readable with no
prompt. Enumerating readers is therefore not a closure — the next
reader nobody listed evades it.

So DX014 also matches a path wordlist against the command's **operand
tokens** (`.aws/credentials`, `.ssh/`, `*.pem`, `.netrc`, `.pgpass`,
`.npmrc`, `.git-credentials`, `.docker/config.json`, gh's `hosts.yml`,
kubeconfig, service-account JSON, `secrets.y[a]ml`), whatever verb
reached them. `matched_text` carries the whole token rather than the
matched span, because the prompt has to name the file at stake.

This is deliberately **not** a general solution. Filesystem permissions
and not storing secrets in readable files remain the real boundaries;
this closes the cases that matter inside an agent session. Keep the
scope honest when extending it: over-firing is what turns DX014 into
noise, so naming a word (`rg pem src/`) or listing a directory
(`ls ~/.ssh`) must stay silent.

Tokenizing goes through `bash_tokens.split_tokens`, not a local
whitespace split — a split shreds a quoted path containing a space into
fragments that match nothing, silently defeating the guarantee. The
pass costs a bounded number of regex searches over short tokens, which
is noise against the hook budget in `.claude/rules/performance.md`; a
heavier mechanism (a real shell parser) would not be, so re-measure
before reaching for one.

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

### DX017 Scopes to the Working Tree, Not the Command (GH-1245)

`cp`, `mv`, `tee`, `touch` and `install` write files without going
through the `Write` tool, so they never reach `validate-edit-write.py`.
DX017 denies such a command **only when the destination resolves inside
the working tree**; a `/tmp` → `/tmp` copy or any write outside the
checkout is left alone.

The scoping is the whole design. Banning the commands outright would be
friction with no safety payoff — shell staging under a scratch root is
legitimate work. What is not legitimate is landing content in the repo
that no one read: GH-1245 records an 866-line script copied in
sight-unseen, and re-doing it as `Read` + `Write` exposed dead `/tmp`
paths, a duplicated block, and useless timing offsets immediately. A
`cp` cannot discover correctness, because copying is not reading. The
skipped validator and the missing `Edit` baseline are the other two
costs.

`HookInput.cwd` stands in for the working tree deliberately. It is
already the checkout root on every hook invocation, and depending on it
keeps DX017 free of a `git rev-parse` subprocess — with the startup
budget gated by `tests/benchmarks/test_startup_time.py`, a subprocess
per Bash call would be the most expensive check in the chain. An empty
`cwd` makes the validator abstain rather than guess.

A new validator that inspects paths should follow the same shape: decide
from the payload the hook already carries, and scope the denial to the
blast radius that motivated it.

**Per-rule config lives in `friction.yaml`, not `settings.json`
(GH-1493).** A project adjusts DX017's blocked extensions with
`dx017: {blocked_extensions: {add: [...], remove: [...]}}` in its
`projects[]` entry. Precedence, lowest first: that key, then
`DEV10X_DX017_BLOCKED_EXTENSIONS` (replaces), `…_EXTRA_…` (adds),
`…_ALLOW_…` (removes). The worktree is probed before its main checkout,
using `domain.linked_worktree` file reads rather than a git subprocess,
and only on the in-tree-write path.

### Live Hints: Steer Without Deciding (GH-1725)

An advisory DX006 rule (`hook_block: false`) may add `live_hint: true`.
The hook then sends the rule's compensation text to the agent as
`additionalContext` before the permission prompt fires.
It emits no `permissionDecision`, so the call proceeds exactly as it
would have.
Use it for a reorder-the-flags nudge, where a deny would be wrong and an
`ask` would re-prompt users who already allow the command.
`live_hint` on a blocking rule, or on a non-Bash rule, is ignored.

1. **A hint never stands in front of a decision.**
   `emit()` exits, so `hook_transport.select_result` picks what is
   emitted: a deny, else an ask, else a deciding allow, else every hint
   merged into one block (GH-1795).
   Iterating `chain.run()` and emitting in order would let a hint emitted
   first hide a later deny.
   A deciding allow carries the hints along as context; a deny or ask
   drops them.
2. **`additionalContext` goes to stdout.**
   That is the stream Claude Code reads it from on an exit-0 hook.
   Every other exit-0 envelope follows the same rule; see § Hook Output
   Streams.
3. **A hint rule needs a quick token like a blocking one.**
   `should_run` drops a command before any rule is evaluated, which is
   why `gog` is in `_QUICK_TOKENS`.
4. **Both rule loaders carry the field.**
   `from_yaml_entry` and the msgpack `_dict_to_config` each set
   `live_hint`.
   A field missing from the cache reverts on every warm load (the
   GH-1084 trap).
5. **The catalog is guarded.**
   `test_every_live_hint_rule_can_actually_steer` fails on a `live_hint`
   rule that blocks, is not Bash, or carries no compensation text.

### Hook Output Streams (GH-1775)

Claude Code parses an exit-0 hook's JSON from **stdout** only, and never
shows Claude an exit-0 hook's stderr. An envelope on stderr is silently
dropped. `hook_transport.emit` owns the contract:

| Result | Exit | Stream | Effect |
|--------|------|--------|--------|
| `HookResult` (deny) | 2 | stderr | Call blocked; stderr reaches Claude |
| `HookAsk` | 0 | stdout | In-session approval prompt (DX014) |
| `HookRetry` | 0 | stdout | PermissionDenied tells the model it may retry |
| `HookHint` | 0 | stdout | `additionalContext` only, no decision |
| `HookAllow(decides=True)` | 0 | stdout | `permissionDecision: "allow"`, prompt skipped |
| `HookAllow` (advisory) | 0 | stdout | No decision; its message, if any, as `additionalContext` |

Until GH-1775 every allow envelope went to stderr, so no allow ever
skipped a prompt. GH-1795 reviewed each one and switched on only the
rule-backed allows, the ones that match a rule the user wrote:

1. DX007 prefix-friction: `uv run` with env flags whose inner command
   matches an allow-rule.
2. DX011 pipeline-allow: every pipeline segment matches an allow-rule.
3. DX014 sensitivity-target: a blessed `sensitivity-exceptions.yaml`
   entry.

DX007 and DX014 match their rule against the whole command string, so
each decides only for a simple command (`bash_tokens.is_simple_command`:
one segment, nothing nested). `foo && rm -rf ~` starts with an allowed
`foo` too. DX011 reads segments through the shared segmenter and
abstains on any operator but `|`, any substitution, and any redirect
other than `/dev/null` or an fd duplicate.

DX001 safe-subshell and DX012 safe-expansion stay advisory. DX012 would
approve `rm -rf $HOME/x` because its metacharacters are inert, and
DX001 judges only the first word (`echo $(git rev-parse HEAD) && rm -rf
~`). DX009 redundant-fetch returns a `HookHint`.

**Precedence is deny > ask > allow, wherever each sits in the chain.**
`select_result` used to stop at the first decision, which was harmless
while an allow decided nothing; once it skips the prompt, a deny later
in the chain must still win. Hints and advisory allows never decide;
their messages ride along as `additionalContext` on a deciding allow.

A new exit-0 envelope goes to stdout and names its `hookEventName`; a
`hookSpecificOutput` without one fails Claude Code's output validation
(GH-1788).

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
`src/dev10x/core/validators/__init__.py` (the typed dataclass replaced the
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

See [`hook-dispatch-patterns.md`](hook-dispatch-patterns.md) for
hook wiring, orchestrators and Stop verdicts.
See `.claude/rules/hook-state-schema.md` for documenting state
schemas. See `.claude/rules/hook-input-patterns.md` for input
validation patterns.
