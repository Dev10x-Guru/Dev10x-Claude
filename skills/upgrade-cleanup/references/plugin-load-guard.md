1. **Copy the guard into userspace** (survives plugin-load failure —
   it must NOT live under the versioned plugin cache):
   - Source: `${CLAUDE_PLUGIN_ROOT}/hooks/scripts/plugin-load-guard.sh`
   - Destination: `~/.claude/hooks/dev10x-plugin-load-guard.sh`
     (create `~/.claude/hooks/` if absent; `chmod 0755` the copy)

2. **Register it as a userspace SessionStart hook** in
   `~/.claude/settings.json` (idempotent — skip if an entry whose
   command ends in `dev10x-plugin-load-guard.sh` already exists):

   ```json
   {
     "hooks": {
       "SessionStart": [
         {
           "matcher": "*",
           "hooks": [
             {
               "type": "command",
               "command": "~/.claude/hooks/dev10x-plugin-load-guard.sh",
               "timeout": 10
             }
           ]
         }
       ]
     }
   }
   ```

   Merge into any existing `SessionStart` array rather than replacing
   it. If the harness does not tilde-expand the command, use the
   absolute path (`/home/<user>/.claude/hooks/...`).

3. **Remove stale versioned-path copies** — delete any prior guard
   registration whose command points into a versioned plugin-cache path
   (`~/.claude/plugins/cache/.../<version>/hooks/scripts/plugin-load-guard.sh`).
   Such a copy defeats the guard's purpose: it disappears exactly when
   plugin discovery is skipped.
