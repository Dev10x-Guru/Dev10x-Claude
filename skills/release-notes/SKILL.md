---
name: Dev10x:release-notes
description: >
  Generate JTBD-driven release notes from git commits between releases.
  Playbook-powered workflow with configurable ticket patterns, output
  targets, and categories.
  TRIGGER when: preparing a release and need to generate changelog or
  release notes from commit history.
  DO NOT TRIGGER when: writing individual commit messages, or updating
  documentation unrelated to releases.
user-invocable: true
invocation-name: Dev10x:release-notes
allowed-tools:
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/release-notes/scripts/collect-prs.py:*)
  - mcp__plugin_Dev10x_cli__collect_prs
  - Bash(gh pr view:*)
  - Bash(gh pr list:*)
  - Bash(gh release edit:*)
  - Bash(gh release view:*)
  - Bash(git tag:*)
  - Bash(git log:*)
  - mcp__claude_ai_Linear__get_issue
  - mcp__claude_ai_Linear__list_issues
  - mcp__claude_ai_Linear__list_comments
  - mcp__claude_ai_Slack__slack_send_message_draft
  - mcp__claude_ai_Slack__slack_read_channel
  - mcp__claude_ai_Slack__slack_search_public
  - mcp__plugin_Dev10x_cli__mktmp
  - AskUserQuestion
  - TaskCreate
  - TaskUpdate
---

# Release Notes Skill

Generate JTBD-driven release notes from git commits between releases.
Uses Job Stories from PR descriptions to produce business-meaningful
summaries instead of technical commit logs.

## When to Use

- A new version has been released and needs release notes
- Asked to write or post release notes
- Asked to summarize changes in a release

## Playbook-Powered Workflow

This skill is driven by playbook configuration. The default playbook
lives at `${CLAUDE_PLUGIN_ROOT}/skills/release-notes/references/playbook.yaml`.
Projects can override via the 4-tier resolution in
`references/config-resolution.md` (global preferred:
`~/.config/Dev10x/playbooks/release-notes.yaml`).

### Plays

| Play | When | Steps |
|------|------|-------|
| `release` | Standard release | collect → generate JTBDs → synthesize → behavior changes → format → post |
| `hotfix` | Hotfix release | collect → short summary → format → post |

### Config Block

Each play has a `config` block with:

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `ticket_patterns` | list[str] | `["[A-Z]+-\\d+"]` | Regex patterns for ticket IDs in commit messages |
| `ticket_links` | dict | `{}` | Prefix → URL template mapping (e.g., `PAY: https://linear.app/team/issue/PAY-{id}`) |
| `output_target` | str | `stdout` | Where to post: `stdout`, `github-release`, or `slack` |
| `slack_channel` | str | null | Slack channel ID (required when output_target is `slack`) |
| `include_joke` | bool | true | Append a release-themed joke |
| `categories` | list[str] | varies | Section headings for grouping changes |

## Workflow

### 1. Load Configuration

1. Read the project playbook override if it exists
2. Fall back to the default playbook
3. Determine which play to use (release vs hotfix)
4. Extract the `config` block for script args and formatting

**Missing override detection:** After loading, check whether a
user override exists (at any tier per `references/config-resolution.md`).
If **no override exists** AND the resolved config has
`output_target: stdout` with empty `ticket_links`:

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text).
Options:
- **Use defaults as-is** — proceed with stdout output, no ticket links
- **Save defaults as project override** — copy the default playbook
  to the project memory directory for future customization
- **Customize key settings now** — interactively set output target
  (stdout / github-release / slack), Slack channel ID, and ticket
  link prefixes, then save as project override

This prevents silent fallback to unusable defaults, which was the
root cause of 3/14 compliance deviations in a prior audit (GH-271).

### 2. Collect PRs

Run the `collect-prs.py` script with configured ticket patterns:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/release-notes/scripts/collect-prs.py \
  <REPO_PATH> \
  [--from TAG] [--to TAG] \
  [--ticket-pattern PATTERN] ...
```

If `--from`/`--to` are omitted, the script auto-detects the two latest tags.

The `--ticket-pattern` arg is repeatable. Pass one per pattern from
the playbook config. Default: `[A-Z]+-\d+` (matches any JIRA/Linear-style ID).

The script outputs structured markdown with:
- Feature PRs with existing JTBDs (ready to use)
- Feature PRs missing JTBDs (need generation)
- Maintenance PRs (no JTBD needed)
- Skipped commits (version bumps, reverts)

Also read the detailed commit messages for context:

```bash
git log <from_tag>..<to_tag> --no-merges --format="### %s%n%n%b%n---"
```

### 3. Generate Missing JTBDs (release play only)

For feature PRs listed as "MISSING JTBDs":

1. Invoke `Dev10x:jtbd` in unattended mode with ticket ID and PR number
2. Collect all drafts
3. Present as a batch for user approval:

> Generated Job Stories for PRs missing them:
>
> - **TICKET-1**: **When** ..., **[actor] wants to** ..., **so [beneficiary] can** ...
> - **TICKET-2**: **When** ..., **[actor] wants to** ..., **so [beneficiary] can** ...
>
> Approve these? (y/edit/n)

### 4. Synthesize Release Summary

**A. Group by business theme** — cluster JTBDs by area. Themes emerge
from the JTBDs themselves; don't force-fit.

**B. Merge related JTBDs** — multiple PRs for the same feature become
a single narrative line.

**C. Identify behavior changes** — scan commit message bodies for:
- Signal/trigger changes
- Auto-completion/auto-close logic changes
- Permission changes
- Default value changes
- Removal or narrowing of behavior

Present any findings to the user before formatting.

**D. Write a 2-3 sentence business summary**:
- Lead with the most impactful change
- Use business language (what users can now do)
- Contrast with the previous state when relevant

### 5. Format Output

Format depends on the configured `output_target`:

#### stdout (default)
Standard markdown output to console.

#### github-release
Markdown formatted for GitHub release body. Post via:
```bash
gh release edit <TAG> --notes-file <NOTES_FILE>
```

#### slack
Slack mrkdwn format with:
- `*bold*` headers (not `##`)
- `•` bullet lists
- `<URL|text>` links
- `:emoji_name:` gitmoji prefixes
- Optional joke at the end (if `include_joke: true`)

### 6. Ticket Links

Generate clickable links based on the `ticket_links` config.
Each entry maps a prefix to a URL template:

```yaml
ticket_links:
  PAY: "https://linear.app/team/issue/{id}"
  TT: "https://org.atlassian.net/browse/{id}"
  GH: "https://github.com/org/repo/issues/{number}"
```

The `{id}` placeholder is replaced with the full ticket ID (e.g., `PAY-123`).
The `{number}` placeholder is replaced with just the numeric part.

### 7. Deliver

Post to the configured target. For Slack, write the formatted message
to a temp file and use the Slack posting mechanism. For GitHub, use
`gh release edit`. For stdout, just print.

## Arguments

```
/Dev10x:release-notes [--play release|hotfix] [--from TAG] [--to TAG]
```

- `--play`: Which playbook play to use (default: `release`)
- `--from`/`--to`: Override auto-detected tags
- Additional args are passed through to collect-prs.py
