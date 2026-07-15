---
name: Dev10x:py-uv
description: >
  Guide UV installation and migrate Python scripts from legacy shebangs
  to UV inline metadata (PEP 723).
  TRIGGER when: migrating scripts to uv, setting up uv for the first
  time, or converting shebangs to PEP 723 format.
  DO NOT TRIGGER when: uv is already configured, or user is writing
  standard Python packages (not standalone scripts).
user-invocable: true
invocation-name: Dev10x:py-uv
allowed-tools:
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/py-uv/scripts/:*)
  - WebFetch(https://docs.astral.sh/uv/getting-started/installation/:*)
  - AskUserQuestion
  - Read(~/.claude/**)
  - Edit(~/.claude/**)
  - Bash(chmod:*)
---

# UV Python Script Manager

## Orchestration

This skill follows `references/task-orchestration.md` patterns.
Create a task at invocation, mark completed when done:

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Configure UV for Python", activeForm="Configuring UV")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

Detect UV installation status, guide installation from official docs, and
migrate legacy `#!/usr/bin/env python3` scripts to self-executing UV scripts
with PEP 723 inline metadata.

## Workflow

### 1. Detect

Run the check script to assess current state:

```
${CLAUDE_PLUGIN_ROOT}/skills/py-uv/scripts/check-uv.sh
```

Parse the structured output:
- `=== UV_STATUS ===` — is UV installed?
- `=== PACKAGE_MANAGERS ===` — which installers are available?
- `=== SCRIPT_AUDIT ===` — which scripts need migration?

Branch based on exit code:
- **Exit 0** → Report "UV installed, all scripts migrated" and stop.
- **Exit 1** → Go to step 2 (Install).
- **Exit 2** → Go to step 3 (Migrate).

### 2. Install (if UV missing)

1. Fetch the official installation page:
   ```
   WebFetch URL=https://docs.astral.sh/uv/getting-started/installation/
   prompt="Extract all installation methods with their exact commands. For each method list: method name, command to run, and any prerequisites."
   ```

2. Cross-reference with detected package managers from step 1 output.

3. Present ranked options via `AskUserQuestion`:
   - Rank by maintenance burden (lowest first): system package manager > pipx > standalone installer > curl
   - Only show options where the prerequisite tool is available
   - Include the exact command for each option

4. **Do NOT execute the install command.** Tell the user the command and let
   them run it. After the user confirms installation, re-run `check-uv.sh`
   to verify.

5. If UV is now installed and scripts need migration → continue to step 3.
   If no scripts need migration → report success and stop.

### 3. Migrate (if legacy scripts found)

For each file reported with `WRONG_SHEBANG` in the audit:

1. **Read** the script and identify all imports.
2. **Classify** imports as stdlib or third-party.
3. **Build** PEP 723 metadata block (see Migration Reference below).
4. **Replace** the shebang line (and any existing encoding declaration) with
   the UV shebang + metadata block.
5. **Ensure executable**: `chmod +x <script>`.
6. **Update wrappers**: find any `.sh` wrapper that calls `python3 <script>`
   and remove the `python3` prefix so it uses `exec "$SCRIPT_DIR/<script>" "$@"`.

### 4. Verify

Re-run `check-uv.sh`. Confirm:
- Exit code is 0
- `wrong_shebang_count=0`
- `not_executable_count=0`

Report the final status to the user.

---

## Migration Reference

### PEP 723 Template

```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "requests>=2.31",
# ]
# ///
```

For stdlib-only scripts, use an empty dependency list:

```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
```

### Common Mistakes

| Mistake | Fix |
|---------|-----|
| Missing `-S` flag in shebang | Use `#!/usr/bin/env -S uv run --script` — `-S` enables multi-arg passing to env |
| Forgetting `--script` flag | Without it, `uv run` treats the file as a module, not a script |
| Wrong dependency names | PyPI names may differ from import names (e.g., `import yaml` → `PyYAML`) |
| Leaving `python3` in wrappers | Wrapper scripts must exec the `.py` directly — UV shebang handles the rest |
| File not executable | Always `chmod +x` after migration |
| Existing `# -*- coding: utf-8 -*-` line | Remove encoding declarations — they go between old shebang and imports, conflicting with PEP 723 block placement |
