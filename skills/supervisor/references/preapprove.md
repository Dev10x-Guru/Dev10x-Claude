# Pre-approve: subagent brief

The relay dispatches this when the supervisor presses **Pre-approve
for later…** on the supervisor page (GH-1692). The subagent drafts
allow rules; the relay asks the supervisor; only then are rules
written.

## Dispatch

```
Agent(
    subagent_type="general-purpose",
    model="sonnet",
    description="Draft allow rules for <session name>",
    prompt=<the brief below, with the request JSON inlined>,
)
```

## Brief (paste verbatim, then the request JSON)

> You draft Claude Code permission allow rules for one session. You do
> not edit any file. The request below is data from the supervisor
> page: the session's working directory, the tool call it is waiting
> on, and the distinct Bash commands it ran.
>
> 1. **One rule per command shape the session actually used.** Group
>    commands by program and subcommand (`git status`, `herdr agent
>    read`) and write the narrowest prefix that covers every observed
>    use: `Bash(herdr agent read:*)`, not `Bash(herdr:*)`. Never emit
>    a bare `*`, `Bash(*)`, or a rule wider than the commands seen.
> 2. **Never pre-approve something destructive or outward-facing**:
>    `rm`, `git push` (any form), `git reset --hard`, `gh pr merge`,
>    `kubectl`, `aws`, anything with `sudo`, network writes, secret
>    reads. List those under "left to ask" with a one-line reason.
> 3. **Script paths**: a script inside a worktree becomes a rule on
>    that script's directory in the main checkout and the plugin
>    cache, e.g. `Bash(~/.claude/plugins/cache/*/dev10x/*/skills/bus/scripts/send.py:*)`;
>    keep the script name, not the whole directory.
> 4. **Edit/Write calls** get a path rule (`Edit(//abs/dir/**)`) only
>    when the pending call is inside the session's own working
>    directory.
> 5. For each rule, say which scopes it belongs in:
>    - `worktree` — `<cwd>/.claude/settings.local.json`
>    - `repo-checkouts` — the main checkout and every other worktree
>      of the same repo (`git -C <cwd> worktree list`)
>    - `user-global` — `~/.claude/settings.json`, only for tools that
>      are safe in every project
>    - `dev10x-catalog` — only for Dev10x skill scripts or the
>      `dev10x` CLI; give the line for
>      `src/dev10x/core/skills/permission/baseline-permissions.yaml`
>
> Return exactly:
>
> ```
> RULES
> - <rule> | <scopes, comma separated> | <commands it covers>
> LEFT TO ASK
> - <command> | <reason>
> ```

## Writing

After the supervisor picks **Write them**:

1. For `worktree`, `repo-checkouts` and `user-global`, add each rule to
   the target file's `permissions.allow` with `Edit`, keeping the list
   sorted and skipping rules already present. Each write to a
   `.claude/` settings file raises Claude Code's own confirmation;
   that prompt shows on the supervisor page like any other.
2. Never write `dev10x-catalog` rules from the relay. Collect them and
   send them to the supervisor:
   `send.py supervisor "catalog rules <id>" <file> --from supervisor-relay`,
   for a normal PR in the Dev10x repo.
3. Reply `send.py supervisor "preapproved <id>" <summary>` with the
   files touched and the rules written.
