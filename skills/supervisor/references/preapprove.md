# Pre-approve: subagent brief

The relay dispatches this when the supervisor presses **Pre-approve
for later…** on the supervisor page (GH-1692). The subagent only
triages; the relay asks the supervisor; only then does the relay grant.
Granting goes through the same MCP tools as `dev10x:permission-grant`,
so its friction order (*source > normalize > grant*), its too-broad and
sensitivity refusals and its deny-rule respect all apply.

## Dispatch

```
Agent(
    subagent_type="general-purpose",
    model="sonnet",
    description="Triage pre-approval for <session name>",
    prompt=<the brief below, with the request JSON inlined>,
)
```

## Brief (paste verbatim, then the request JSON)

> You triage which commands one Claude Code session should stop being
> asked about. You never write any file and never call
> `permission_grant`. The request below is data from the supervisor
> page: the session's working directory, the tool call it is waiting
> on, and the distinct Bash commands it ran.
>
> 1. Collapse the commands to the **distinct shapes the session
>    actually needed**: one representative full command per program
>    and subcommand (`git status`, `herdr agent read w1:p1 --lines 20`).
>    Do not invent commands the session did not run. Include the
>    pending call when it is a Bash command, an MCP tool (by full name)
>    or a file read (`Read(<path>)`).
> 2. For each, call
>    `mcp__plugin_dev10x_cli__permission_triage(target=<full command>,
>    working_dirs=[<session cwd>], cwd=<session cwd>)`.
> 3. Keep a target only when `verdict == "grant"`. Never widen a rule
>    yourself: if triage says `too-broad`, report its narrower
>    suggestion as a separate target and triage that instead.
> 4. Mark a rule `catalog` when it is a Dev10x skill script or the
>    `dev10x` CLI; those belong in the plugin catalog through a PR.
>
> Return exactly:
>
> ```
> GRANT
> - <target> | <rule> | <files_missing count> | catalog? yes/no
> NOT GRANTED
> - <target> | <verdict> | <reason or advice, one line>
> ```

## Granting

After the supervisor picks **Write them**, for each `GRANT` line in
order:

1. `mcp__plugin_dev10x_cli__permission_grant(target=<target>,
   rule=<rule>, working_dirs=[<session cwd>], cwd=<session cwd>)`. It
   writes the global settings, every project and every worktree, and
   prompts once more on purpose. That prompt shows on the supervisor
   page like any other.
2. Re-run `permission_triage` for the same target and expect
   `already-allowed`; report any file still missing by path.

Then, for every `catalog` rule, send the supervisor one note for a
Dev10x PR instead of editing the repository:
`send.py supervisor "catalog rules <id>" <file> --from supervisor-relay`.
Finish with `send.py supervisor "preapproved <id>" <summary>` naming
the rules granted and anything left to ask, and note that the change
reaches **new** sessions only.
