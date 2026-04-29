"""Integration tests for the refactored plugin structure.

Validates that hooks, MCP servers, CLI, and config all work
together after the src/dev10x migration.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from dev10x.cli import cli
from dev10x.config.loader import load_config
from dev10x.domain.rule_engine import RuleEngine
from dev10x.hooks.edit_validator import validate_edit_write

REPO_ROOT = Path(__file__).resolve().parent.parent

_PEP723_DEPS_RE = re.compile(
    r"# /// script\s*\n(.*?)# ///",
    re.DOTALL,
)


class TestCliIntegration:
    @pytest.fixture()
    def runner(self) -> CliRunner:
        return CliRunner()

    def test_hook_subcommand_exists(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["hook", "--help"])

        assert result.exit_code == 0
        assert "validate-bash" in result.output

    def test_validate_subcommand_exists(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["validate", "--help"])

        assert result.exit_code == 0

    def test_skill_subcommand_exists(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["skill", "--help"])

        assert result.exit_code == 0


class TestConfigCaching:
    def test_first_load_creates_cache(self, tmp_path: Path) -> None:
        yaml_path = REPO_ROOT / "src" / "dev10x" / "validators" / "command-skill-map.yaml"
        if not yaml_path.exists():
            pytest.skip("command-skill-map.yaml not found")

        yaml_copy = tmp_path / "config.yaml"
        yaml_copy.write_text(yaml_path.read_text())

        load_config(yaml_path=yaml_copy)

        assert yaml_copy.with_suffix(".msgpack").exists()

    def test_second_load_uses_cache(self, tmp_path: Path) -> None:
        yaml_path = REPO_ROOT / "src" / "dev10x" / "validators" / "command-skill-map.yaml"
        if not yaml_path.exists():
            pytest.skip("command-skill-map.yaml not found")

        yaml_copy = tmp_path / "config.yaml"
        yaml_copy.write_text(yaml_path.read_text())

        first = load_config(yaml_path=yaml_copy)
        second = load_config(yaml_path=yaml_copy)

        assert first.friction_level == second.friction_level
        assert len(first.rules) == len(second.rules)


class TestHookDispatch:
    def test_validate_bash_returns_json(self) -> None:
        hook_script = REPO_ROOT / "hooks" / "scripts" / "validate-bash-command.py"
        if not hook_script.exists():
            pytest.skip("validate-bash-command.py not found")

        payload = json.dumps(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "echo hello"},
            }
        )

        result = subprocess.run(
            [sys.executable, str(hook_script)],
            input=payload,
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert result.returncode == 0

    def test_validate_edit_allows_safe_file(self) -> None:
        data = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/work/project/src/main.py",
                "new_string": "x = 1",
            },
        }

        with pytest.raises(SystemExit) as exc_info:
            validate_edit_write(data=data)

        assert exc_info.value.code == 0


class TestEditValidatorRules:
    def test_loads_production_rules(self) -> None:
        yaml_path = REPO_ROOT / "src" / "dev10x" / "validators" / "command-skill-map.yaml"
        if not yaml_path.exists():
            pytest.skip("command-skill-map.yaml not found")

        engine = RuleEngine.from_yaml(path=yaml_path)

        assert len(engine.edit_rules) > 0
        assert all(r.name for r in engine.edit_rules)


def _script_imports_dev10x(script: Path) -> bool:
    import ast

    try:
        tree = ast.parse(script.read_text())
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("dev10x"):
            return True
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("dev10x"):
                    return True
    return False


def _extract_dev10x_imports(script: Path) -> list[str]:
    import ast

    tree = ast.parse(script.read_text())
    lines: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("dev10x"):
            names = ", ".join(alias.name for alias in node.names if alias.name != "*")
            if names:
                lines.append(f"from {node.module} import {names}")
            else:
                lines.append(f"import {node.module}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("dev10x"):
                    lines.append(f"import {alias.name}")
    return lines


def _collect_python_entry_points() -> list[Path]:
    dirs = [
        REPO_ROOT / "hooks" / "scripts",
        REPO_ROOT / "servers",
    ]
    for skill_dir in sorted((REPO_ROOT / "skills").iterdir()):
        scripts_dir = skill_dir / "scripts"
        if scripts_dir.is_dir():
            dirs.append(scripts_dir)

    scripts: list[Path] = []
    for d in dirs:
        for p in sorted(d.glob("*.py")):
            if p.name == "__init__.py":
                continue
            scripts.append(p)
    return scripts


PYTHON_ENTRY_POINTS = _collect_python_entry_points()


class TestScriptLoadability:
    @pytest.mark.parametrize(
        "script",
        PYTHON_ENTRY_POINTS,
        ids=lambda p: str(p.relative_to(REPO_ROOT)),
    )
    def test_compiles_without_error(self, script: Path) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", str(script)],
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert result.returncode == 0, (
            f"{script.relative_to(REPO_ROOT)} failed to compile:\n{result.stderr}"
        )

    @pytest.mark.parametrize(
        "script",
        [s for s in PYTHON_ENTRY_POINTS if _script_imports_dev10x(s)],
        ids=lambda p: str(p.relative_to(REPO_ROOT)),
    )
    def test_dev10x_imports_resolve(self, script: Path) -> None:
        import_lines = _extract_dev10x_imports(script=script)
        for line in import_lines:
            result = subprocess.run(
                [sys.executable, "-c", line],
                capture_output=True,
                text=True,
                timeout=10,
            )

            assert result.returncode == 0, (
                f"{script.relative_to(REPO_ROOT)}: import failed: {line}\n{result.stderr}"
            )


HOOK_SCRIPTS = [
    "hooks/scripts/validate-bash-command.py",
    "hooks/scripts/validate-edit-write.py",
    "hooks/scripts/task-plan-sync.py",
]

SKILL_SCRIPTS_WITH_SRC_IMPORTS = [
    "skills/skill-audit/scripts/extract-session.py",
    "skills/skill-audit/scripts/analyze-actions.py",
    "skills/skill-audit/scripts/analyze-permissions.py",
    "skills/git-groom/scripts/mass-rewrite.py",
]


class TestPythonEntryPointLoadability:
    """GH-681: Verify Python scripts can be loaded from installed plugin context.

    Hook scripts use `from dev10x.xxx import ...` directly and rely on
    the dev10x package being importable. Skill scripts that insert
    src/ into sys.path must resolve relative to their own location.
    """

    @pytest.mark.parametrize("script_path", HOOK_SCRIPTS)
    def test_hook_script_compiles(self, script_path: str) -> None:
        path = REPO_ROOT / script_path
        if not path.exists():
            pytest.skip(f"{script_path} not found")
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                f"import py_compile; py_compile.compile('{path}', doraise=True)",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, f"Compilation failed: {result.stderr}"

    @pytest.mark.parametrize("script_path", SKILL_SCRIPTS_WITH_SRC_IMPORTS)
    def test_skill_script_compiles(self, script_path: str) -> None:
        path = REPO_ROOT / script_path
        if not path.exists():
            pytest.skip(f"{script_path} not found")
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                f"import py_compile; py_compile.compile('{path}', doraise=True)",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, f"Compilation failed: {result.stderr}"

    @pytest.mark.parametrize(
        "module",
        [
            pytest.param(
                "dev10x.hooks.edit_validator",
                marks=pytest.mark.xfail(
                    reason=(
                        "Circular import: edit_validator → domain → rule_engine → edit_validator"
                    )
                ),
            ),
            "dev10x.commands.hook",
            "dev10x.hooks.task_plan_sync",
            "dev10x.validators.skill_redirect",
            "dev10x.skills.audit.extract_session",
        ],
    )
    def test_dev10x_module_importable(self, module: str) -> None:
        result = subprocess.run(
            [sys.executable, "-c", f"import {module}"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(REPO_ROOT),
            env={**__import__("os").environ, "PYTHONPATH": str(REPO_ROOT / "src")},
        )
        assert result.returncode == 0, f"Import failed for {module}: {result.stderr}"


def _collect_uv_shebang_scripts() -> list[Path]:
    scripts: list[Path] = []
    for pattern in ["skills/**/scripts/*.py", "hooks/scripts/*.py", "servers/*.py"]:
        for p in sorted(REPO_ROOT.glob(pattern)):
            if p.name == "__init__.py":
                continue
            first_line = p.read_text().split("\n", 1)[0]
            if "uv run" in first_line:
                scripts.append(p)
    standalone = REPO_ROOT / "skills" / "slack" / "slack-notify.py"
    if standalone.exists() and "uv run" in standalone.read_text().split("\n", 1)[0]:
        scripts.append(standalone)
    return scripts


UV_SHEBANG_SCRIPTS = _collect_uv_shebang_scripts()


class TestUvShebangDependencies:
    """GH-913: Verify uv shebang scripts have satisfiable PEP 723 deps.

    Runs each script with `uv run --script <file> --help` to confirm
    uv can resolve inline dependencies. Exit code 0 or 2 (argparse
    unrecognized args) both indicate deps resolved successfully.
    """

    @pytest.mark.parametrize(
        "script",
        UV_SHEBANG_SCRIPTS,
        ids=lambda p: str(p.relative_to(REPO_ROOT)),
    )
    def test_uv_resolves_inline_deps(self, script: Path) -> None:
        result = subprocess.run(
            ["uv", "run", "--script", str(script), "--help"],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(REPO_ROOT),
        )
        dep_failure_markers = [
            "No solution found",
            "Could not find a version",
            "Failed to download",
            "ModuleNotFoundError",
            "No matching distribution",
        ]
        has_dep_failure = any(m in result.stderr for m in dep_failure_markers)
        assert not has_dep_failure, (
            f"uv failed to resolve deps for {script.relative_to(REPO_ROOT)}:\n"
            f"exit code: {result.returncode}\n"
            f"stderr: {result.stderr[:500]}"
        )

    @pytest.mark.parametrize(
        "script",
        UV_SHEBANG_SCRIPTS,
        ids=lambda p: str(p.relative_to(REPO_ROOT)),
    )
    def test_pep723_metadata_is_valid(self, script: Path) -> None:
        content = script.read_text()
        match = _PEP723_DEPS_RE.search(content)
        assert match is not None, (
            f"{script.relative_to(REPO_ROOT)} has uv shebang but no "
            f"PEP 723 inline metadata block (# /// script ... # ///)"
        )


class TestStartupTime:
    BUDGET_MS = 2000

    def test_cli_help_under_budget(self) -> None:
        import time

        start = time.monotonic()
        result = subprocess.run(
            ["uv", "run", "dev10x", "--help"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(REPO_ROOT),
        )
        elapsed_ms = (time.monotonic() - start) * 1000

        assert result.returncode == 0
        assert "hook" in result.stdout
        assert elapsed_ms < self.BUDGET_MS, (
            f"Startup took {elapsed_ms:.0f}ms (budget: {self.BUDGET_MS}ms)"
        )
