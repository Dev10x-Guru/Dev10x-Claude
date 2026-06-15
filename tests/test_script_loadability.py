"""Verify Python entry points load without dev10x on PYTHONPATH.

When executed from an installed plugin, sys.path may not include
the src/ directory. Each script must handle this via sys.path
manipulation or try/except ImportError fallback.

These tests run each script in a subprocess with a clean PYTHONPATH
to simulate the installed plugin environment.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

HOOK_SCRIPTS = sorted(
    (REPO_ROOT / "hooks" / "scripts").glob("*.py"),
)

SKILL_SCRIPTS = sorted(
    REPO_ROOT.glob("skills/**/scripts/*.py"),
)

SKILL_STANDALONE_SCRIPTS = [
    REPO_ROOT / "skills" / "slack" / "slack-notify.py",
]

SERVER_SCRIPTS = [
    p for p in sorted((REPO_ROOT / "servers").glob("*.py")) if p.name != "__init__.py"
]

ALL_ENTRY_POINTS = HOOK_SCRIPTS + SKILL_SCRIPTS + SKILL_STANDALONE_SCRIPTS + SERVER_SCRIPTS

_PEP723_DEPS_RE = re.compile(
    r"# /// script\s*\n(.*?)# ///",
    re.DOTALL,
)
_DEP_NAME_RE = re.compile(r'"([^"]+)"')

PROJECT_PACKAGES = {"dev10x", "pyyaml", "click", "mcp"}


def _extract_external_deps(script: Path) -> list[str]:
    content = script.read_text()
    match = _PEP723_DEPS_RE.search(content)
    if not match:
        return []
    deps_block = match.group(1)
    deps: list[str] = []
    in_deps = False
    for line in deps_block.splitlines():
        stripped = line.lstrip("# ").strip()
        if stripped.startswith("dependencies"):
            in_deps = True
        if in_deps:
            for dep_match in _DEP_NAME_RE.finditer(line):
                raw = dep_match.group(1)
                dep_name = re.split(r"[><=!;\[]", raw)[0].strip().lower()
                if dep_name and dep_name not in PROJECT_PACKAGES:
                    deps.append(dep_name)
        if in_deps and "]" in line:
            in_deps = False
    return deps


def _has_missing_deps(script: Path) -> str | None:
    external_deps = _extract_external_deps(script=script)
    for dep in external_deps:
        import_name = dep.replace("-", "_")
        if importlib.util.find_spec(import_name) is None:
            return dep
    return None


def _script_id(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


@pytest.mark.parametrize("script", ALL_ENTRY_POINTS, ids=_script_id)
class TestScriptLoadability:
    def test_script_parses_without_syntax_errors(self, script: Path) -> None:
        result = subprocess.run(
            [sys.executable, "-c", f"import ast; ast.parse(open('{script}').read())"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, f"Syntax error in {script.name}: {result.stderr}"

    def test_script_imports_resolve_from_repo(self, script: Path, tmp_path: Path) -> None:
        missing = _has_missing_deps(script=script)
        if missing:
            pytest.skip(f"External dependency {missing!r} not installed")

        src_dir = str(REPO_ROOT / "src")
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    f"import sys; sys.path.insert(0, '{src_dir}'); "
                    f"import importlib.util; "
                    f"spec = importlib.util.spec_from_file_location('_test', '{script}'); "
                    f"mod = importlib.util.module_from_spec(spec); "
                    f"spec.loader.exec_module(mod)"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            env={"PATH": "", "HOME": str(tmp_path)},
        )
        assert result.returncode == 0, (
            f"Failed to load {script.name} with src/ on path: {result.stderr}"
        )


EXECUTABLE_SCRIPTS = sorted(
    [p for p in REPO_ROOT.glob("skills/**/scripts/*") if p.suffix in (".py", ".sh")]
    + [p for p in (REPO_ROOT / "hooks" / "scripts").iterdir() if p.suffix in (".py", ".sh")]
)


@pytest.mark.parametrize("script", EXECUTABLE_SCRIPTS, ids=_script_id)
class TestScriptPermissions:
    def test_script_has_execute_permission(self, script: Path) -> None:
        assert script.stat().st_mode & 0o111, (
            f"{script} lacks execute permission — run `chmod +x {script.relative_to(REPO_ROOT)}`"
        )


SCRIPTS_WITH_DEV10X_IMPORTS = [
    s
    for s in ALL_ENTRY_POINTS
    if "from dev10x" in s.read_text() or "import dev10x" in s.read_text()
]


@pytest.mark.parametrize("script", SCRIPTS_WITH_DEV10X_IMPORTS, ids=_script_id)
class TestScriptSysPathFallback:
    def test_script_has_sys_path_fallback(self, script: Path) -> None:
        content = script.read_text()
        has_sys_path_insert = "sys.path.insert" in content
        has_import_error_fallback = "except ImportError" in content
        assert has_sys_path_insert or has_import_error_fallback, (
            f"{script.name} imports from dev10x but lacks sys.path.insert "
            f"or ImportError fallback — will fail from installed plugin"
        )
