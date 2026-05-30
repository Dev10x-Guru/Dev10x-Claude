# PEP 660 / Editable-Install vs ADD_CONTENT_ROOTS Conflict

## Root Cause

PyCharm's Python run-config defaults ship with:

```xml
<option name="ADD_CONTENT_ROOTS" value="true" />
<option name="ADD_SOURCE_ROOTS" value="true" />
```

These flags inject `<repo>/src` (and other content/source roots) onto
`PYTHONPATH` before the interpreter starts. They exist as a workaround for
scripting projects that never grew a `pyproject.toml` and therefore have no
installed package path.

## Why This Breaks Editable Installs

**Editable install** (PEP 660, `pip install -e .`, `uv pip install -e .`,
uv workspace members) installs the package into the venv's site-packages via
a `.pth` file or a direct `.dist-info/direct_url.json` link. The package
import path comes from the venv — `PYTHONPATH` is not needed and actively
harmful.

When `ADD_CONTENT_ROOTS=true` is combined with an editable install:

1. PyCharm prepends `<repo>/src` to `PYTHONPATH`
2. Python's import machinery resolves packages from `PYTHONPATH` first
3. `site.py` runs, processes `.pth` files from the venv
4. Any `sitecustomize.py` in the venv's site-packages is executed
5. **New Relic's bootstrap loader** (canonical victim): `newrelic/bootstrap/sitecustomize.py`
   patches `sys.modules['collections']` before `collections.abc` is importable
   under uv-managed Python, causing:

```
ModuleNotFoundError: No module named 'collections.abc'; 'collections' is not a package
```

The same failure appears for any other `sitecustomize`-bootstrapping agent
(DataDog APM, OpenTelemetry auto-instrumentation, coverage.py bootstrap, etc.).

## The Two-Step Trap

The failure symptom (`uv run /path/.venv/bin/python …`) and the root cause
(PYTHONPATH side-channel activating `sitecustomize`) are two steps apart:

1. PyCharm uv-SDK FLAVOR_DATA gap causes the wrong launch command
2. ADD_CONTENT_ROOTS activates sitecustomize which crashes under that command

Each step alone is survivable. Combined, they produce a crash that costs
30–45 minutes of debugging because the traceback points to `sitecustomize`
rather than the run-config flags.

## Fix

Disable both flags on every Python run config in `.idea/workspace.xml`:

```xml
<option name="ADD_CONTENT_ROOTS" value="false" />
<option name="ADD_SOURCE_ROOTS" value="false" />
```

Projects using editable installs (the correct pattern for any project with
`pyproject.toml`) never need these flags. Disabling them is safe and the
correct default for modern Python projects.

## Public Documentation

- PEP 660: Editable installs for `pyproject.toml`-based builds
  <https://peps.python.org/pep-0660/>
- uv workspace members: editable by default
  <https://docs.astral.sh/uv/concepts/workspaces/>
- PyCharm: "Add content roots to PYTHONPATH" setting
  (JetBrains docs, Python run/debug configuration)
