# Maintenance in an auto mode session

A session that runs in auto mode (`disableAutoMode` opted out, GH-1856)
has a classifier between the agent and every tool call. During the
0.115.0 maintenance pass it denied three steps of this flow (GH-1868):

| Step | What was denied |
|------|-----------------|
| Applying an approved audit finding | `Read` of the user-level `settings.local.json` to find the rule |
| Applying an approved audit finding | `Edit` adding an allow rule to the user `settings.json` — "self-modification" |
| upgrade-cleanup Step 3 (plugin-load guard) | Searching settings for the guard's registration |

The second denial came after the paired ask removal had already
succeeded, so the change landed half-applied.

## What to do

1. **Expect it for user-level files.** Reads and writes of
   `~/.claude/settings*.json` are the ones the classifier refuses.
   Project files (`<repo>/.claude/settings.local.json`) normally pass.
2. **Order paired edits so the restrictive half lands first.** Add the
   new rule before removing the old one (allow added, then ask
   removed). If the second edit is denied, the file is stricter than
   intended, never looser and never missing both rules.
3. **On a denial, stop that step — do not retry it another way.** A
   shell `sed`, a `cp` of an edited copy, or a script that writes the
   file is the same self-modification by another route, and the
   plugin's own hooks deny most of them anyway.
4. **Hand the exact change to the supervisor.** Name the file, the
   list (`allow` / `ask` / `deny`) and the rule, and say whether it
   adds or removes. Record it in the summary as "handed over", and
   continue with the project-level steps.
5. **Never substitute a global rule for a denied project one.** A rule
   in `~/.claude/settings.json` does not reliably reach a project that
   has its own `settings.local.json` (GH-47), so it looks applied and
   changes nothing. The supervisor's standing intent: fix project
   settings; leave global ones to them.
