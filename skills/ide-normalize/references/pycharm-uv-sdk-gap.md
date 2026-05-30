# PyCharm uv-SDK FLAVOR_DATA Gap

## Symptom

After PyCharm auto-creates a `uv (<worktree-name>)` SDK for a new worktree,
`manage.py runserver` (or any other run config) crashes with:

```
$ uv run /work/.../encom-pos-6/.venv/bin/python manage.py runserver ...
Error in sitecustomize; set PYTHONVERBOSE for traceback:
ModuleNotFoundError: No module named 'collections.abc'; 'collections' is not a package
```

The launch command `uv run /full/path/.venv/bin/python ...` is wrong.
The correct command is `uv run python ...` (uv resolves the venv implicitly).

## Root Cause

When PyCharm discovers a new worktree's `.venv/` and creates a SDK entry, it
writes an `<additional>` block in `jdk.table.xml` with empty `FLAVOR_DATA`:

```xml
<!-- Broken (auto-created for worktree): -->
<additional ASSOCIATED_PROJECT_PATH="/work/.../encom-pos-6"
            IS_UV="true"
            UV_WORKING_DIR="/work/.../encom-pos-6">
  <setting name="FLAVOR_DATA" value="{}" />
</additional>
```

Without `UV_VENV_PATH` and `UV_TOOL_PATH`, PyCharm does not know how to
invoke `uv` as a launcher and falls back to the interpreter binary directly,
passing it as a `uv run <binary>` argument instead of letting uv manage the
venv.

## Working SDK (Parent Project)

```xml
<!-- Working (manually configured for parent project): -->
<additional ASSOCIATED_PROJECT_PATH="/work/.../encom-pos"
            IS_UV="true"
            UV_WORKING_DIR="/work/.../encom-pos"
            UV_VENV_PATH="/work/.../encom-pos/.venv"
            UV_TOOL_PATH="/home/user/.local/bin/uv">
  <setting name="FLAVOR_DATA"
           value="{&quot;uvWorkingDirectory&quot;:&quot;/work/.../encom-pos&quot;,
                   &quot;usePip&quot;:false,
                   &quot;venvPath&quot;:&quot;/work/.../encom-pos/.venv&quot;,
                   &quot;uvPath&quot;:&quot;/home/user/.local/bin/uv&quot;}" />
</additional>
```

## Detection

1. Locate `jdk.table.xml`:
   - Linux: `~/.config/JetBrains/PyCharm<version>/options/jdk.table.xml`
   - macOS: `~/Library/Application Support/JetBrains/PyCharm<version>/options/jdk.table.xml`
2. Find SDK entries with `ASSOCIATED_PROJECT_PATH` matching the worktree path
3. Check for `FLAVOR_DATA="{}"` or missing `UV_VENV_PATH` / `UV_TOOL_PATH`

## Patch Recipe (PyCharm must be closed)

PyCharm overwrites `jdk.table.xml` on exit. The file must be patched while
PyCharm is **not running**.

Replace the broken `<additional>` block with a copy of the parent project's
block, substituting the worktree path values:

```xml
<additional ASSOCIATED_PROJECT_PATH="<worktree-path>"
            IS_UV="true"
            UV_WORKING_DIR="<worktree-path>"
            UV_VENV_PATH="<worktree-path>/.venv"
            UV_TOOL_PATH="<uv-binary-path>">
  <setting name="FLAVOR_DATA"
           value="{&quot;uvWorkingDirectory&quot;:&quot;<worktree-path>&quot;,
                   &quot;usePip&quot;:false,
                   &quot;venvPath&quot;:&quot;<worktree-path>/.venv&quot;,
                   &quot;uvPath&quot;:&quot;<uv-binary-path>&quot;}" />
</additional>
```

Values to substitute:
- `<worktree-path>`: absolute path to the worktree (e.g. `/work/encom/encom-pos-6`)
- `<uv-binary-path>`: `which uv` output (e.g. `/home/user/.local/bin/uv`)

## Manual Fix (Alternative)

If you prefer not to patch the file directly:

1. Close PyCharm
2. Open PyCharm, open the worktree project
3. Go to **Settings → Project → Python Interpreter**
4. Click the interpreter selector → **Add New Interpreter → Add Local Interpreter**
5. Select **uv** and pick the `.venv/` inside the worktree
6. Apply and close Settings

This re-creates the SDK entry correctly via the IDE UI.

## Upstream Status

This is a PyCharm bug: the IDE should populate `UV_VENV_PATH`, `UV_TOOL_PATH`,
and `FLAVOR_DATA` when auto-creating a uv SDK entry for a worktree that already
has a `.venv/`. No upstream fix is available as of PyCharm 2024.x.

Workaround: use `Dev10x:ide-normalize` immediately after creating a new
worktree, before opening PyCharm against it.
