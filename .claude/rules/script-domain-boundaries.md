# Script vs Domain Boundaries (GH-246 H3/H7)

How skill **entry-point scripts** and in-process **`dev10x` domain
functions** differ in output and error handling. Ratified by
[`docs/adr/0010-uv-script-skills-as-importable-modules.md`](../../docs/adr/0010-uv-script-skills-as-importable-modules.md).

Skill logic lives in importable `dev10x.skills.*` modules; uv-script
entry points are thin shims. The two layers report results
differently, and mixing the conventions is a defect.

## Output convention (H3)

| Layer | Rule |
|-------|------|
| Entry-point script (`skills/**/scripts/*.py`, a `main()`) | Write user-facing output to **stdout** and diagnostics to **stderr** via `print()`. |
| In-process domain function (`dev10x.*`) | Use structured **`logging`**, never `print()`. |

Only a script's `main()` (or its argparse glue) translates a domain
result into printed output. A domain function that calls `print()` is
a defect — it cannot be reused by the MCP boundary, which captures
return values, not stdout.

## Error convention (H7)

| Layer | Rule |
|-------|------|
| In-process domain function | Return `Result[T]` (`ok(...)` / `err(...)`), per [ADR-0009](../../docs/adr/0009-result-contract-at-mcp-boundary.md). Never call `sys.exit`. |
| Entry-point script | Own process exit: map a domain failure to `sys.exit(N)` with a stderr message. |

### Single-channel rule for parsed scripts

When a script's **stdout is parsed** by an MCP wrapper or another tool
(it prints a JSON verdict, list, etc.), it MUST emit its error as a
JSON object on **stdout** too — not stderr — so the consumer parses
one channel and never sees empty stdout on failure.

Example (`ci_check_status`): the verdict JSON and the
`{"error": "..."}` blob both go to stdout; the script still exits
non-zero so shell callers can branch on the exit code.

A genuinely-unknown state is not an error: `ci_check_status`'s
`fetch_mergeable` returns `"UNKNOWN"` (a valid verdict input) while
GitHub is still computing mergeability — it does not raise or exit.

## Reviewer checklist

- Domain function uses `logging`, returns `Result[T]`, no `sys.exit`,
  no `print()`.
- Script `main()` owns exit codes and printed output.
- A stdout-parsed script emits errors as JSON on stdout, exits
  non-zero.
