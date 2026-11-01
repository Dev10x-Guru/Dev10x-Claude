# diag-friction Step Details

Procedures moved out of `SKILL.md` to keep it near its line budget
(GH-1727). `SKILL.md` keeps each step's purpose, its gates, and the
Step 3h routing table; read the matching section here when the step
applies.

## Step 3a: Effective-file coverage (GH-1139)

**Run this BEFORE the shape audit.** The most common cause of a
prompt on a seeded machine is not a missing rule — it is a rule
that exists in the catalog and in global but not in the file the
engine actually reads (GH-1136). Diagnosing the individual command
first hides that layer, which is how a worktree stayed "constantly
stuck on basic actions" while every diag-friction run answered a
different question.

1. Resolve the effective settings file for the CWD: the worktree's
   `.claude/settings.local.json`, else the project's, else global.
2. Run the catalog-gap check and read the counts by family:

   ```
   mcp__plugin_dev10x_cli__permission_catalog_gap()
   ```

   Returns `total_missing`, `files_checked`, `clean`, and the
   per-family `messages`. Pass `verbose=true` to list every missing
   rule rather than the counts. `out_of_roots` lists worktrees found
   through `git worktree list` that sit under no configured root
   (GH-1626). They are checked like any other file; a non-empty list
   means `roots` is missing a location, so mention it in the report.

   **Fallback — Bash** (only when the MCP server is unavailable):

   ```bash
   uvx dev10x permission catalog-gap
   ```

   Prefer the MCP form (GH-1175): without a `Bash(uvx:*)` rule the
   Bash form prompts, and in a background agent that prompt silently
   skips the coverage check.

3. If the offending command's generalized rule (Step 3d) is in the
   catalog but absent from the effective file, say so **first**:
   the diagnosis is a **propagation gap**, not a missing rule.

**Three-outcome routing for Step 4.** Distinguish these — they have
different fixes, and conflating (a) with (b) patches per-repo while
hiding the propagation defect:

| Outcome | Condition | Fix |
|---------|-----------|-----|
| (a) propagation gap | rule in catalog, missing from effective file | backfill (SKILL.md Step 3a gate) |
| (b) missing default | rule absent from catalog, generally safe | upstream issue (Step 3c), plus the Step 3h grant now |
| (c) project-specific | safe only for this project | Step 3h: triage, then `dev10x:permission-grant` |

See [`audit-procedure.md`](audit-procedure.md) § Effective-file
coverage for the resolution order and the two sanctioned
settings-read surfaces.

## Step 3c-pre: Inline-code structured-alternatives (GH-282)

When the offending command starts with an inline-code prefix
(`python -c`, `python3 -c`, `sh -c`, `bash -c`, `perl -e`,
`ruby -e`, `node -e`, `deno eval`), the right recommendation is
almost never "extract to `~/.claude/tools/`" — it's the canonical
structured tool that already exists for the use case (jq, yq,
yamllint, actionlint, curl, etc.).

1. `Read(file_path="${CLAUDE_PLUGIN_ROOT}/skills/diag-friction/references/structured-alternatives.yaml")`
2. Check the offending command against `inline_code_prefixes`. If
   no prefix matches, skip this step and proceed to Step 3c.
3. Extract the inline code body (text between the quotes after the
   `-c` / `-e` flag).
4. Match the body against each entry's `detection_keywords`
   (substring match; first hit wins).
5. Surface the matched `tool` and `example` as the **primary**
   recommendation in the "Use instead" section of Step 4.
6. Fall back to the "Multi-step logic (fallback)" entry only when
   no keyword matches across all other entries.

Example match for `python -c "import yaml; yaml.safe_load(...)"`:
the `yaml.safe_load` keyword hits the YAML-parsing entry, so the
reinforcement names `yq` as the canonical alternative — not a
tools-directory extraction.

## Step 3d: Generalize the suggested rule shape (GH-597)

When the audit (Step 3b) or upstream path (Step 3c) lands on
proposing a **targeted allow-rule**, do not echo the harness's
suggested shape — it is wrong in one of three directions. Surface
the generalized shape produced by
`dev10x.skills.permission.generalize.generalize_rule_shape`:

| Failure mode | Harness suggests | Generalized shape |
|--------------|------------------|-------------------|
| over-broad (verb-blind) | `Bash(ip route *)` | `Bash(ip route get:*)` |
| over-narrow (session arg) | `Bash(persist.sh <id> *)` | `Bash(persist.sh:*)` |
| too-literal (no wildcard) | `Bash(yarn build:x)` | `Bash(yarn build:*)` |

Apply the generalized rule in the "Pre-approved alternatives" /
"Upstream issue" sections so the rule the user accepts is reusable
and safe — never the dead-on-arrival or over-granting default.
Only Bash command rules are generalized; `mcp__*`, `WebFetch(...)`,
and `Read(...)` rules pass through unchanged.

## Step 3e: Background-dispatch pre-seed over auto-mode (GH-610)

When the friction arose inside a **background subagent** (workflow /
monitor / loop / fanout child) — or the only "fix" on offer is the
harness's "switch to auto mode" / disable-prompts nudge (the GH-310
footgun) — do NOT recommend blanket `bypassPermissions`. The correct
remedy is to fix the **dispatcher**, not to silence prompts:

1. Prepend the canonical friction-avoidance preamble to the subagent
   prompt (fetch via `mcp__plugin_dev10x_cli__background_preamble`).
2. Pre-seed the subagent's `allowed_tools` with the wrappers it needs
   (`Read`, `Grep`, `Glob`, `mktmp`, `push_safe`, `create_pr`, …) so
   the preferred tool surface is actually available. When the child
   was refused a project script, add that script's rule to the list
   too, naming the dispatcher and the exact entry.
3. When Step 3h triage returns `grant`, also write the rule through
   `dev10x:permission-grant`: a pre-seeded list never reaches the
   settings files, and an unattended child has nobody to answer the
   next prompt.

Surface this as the primary recommendation whenever the offending
command came from a background dispatch path. See
`references/orchestration/background-preamble.md` and
`references/orchestration/subagent-dispatch.md` § Background Friction
Preamble.
