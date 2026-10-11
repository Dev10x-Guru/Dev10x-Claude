"""Pin which CI legs the change classifier selects (GH-1595).

``hook-tests`` and ``server-tests`` used to be selected by hand-kept path
globs. Those fell behind the ADR-0034 Stage A moves, so PRs that changed
modules the hook and server entry points import merged with both suites
skipped. These tests walk the real import closure of ``hooks/scripts/*.py``
and ``servers/*.py`` and run the actual classifier script against a
throwaway repository, so a module the suites reach can never again be
filtered out.
"""

from __future__ import annotations

import ast
import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).parents[1]
_SRC_ROOT = _REPO_ROOT / "src"
_CLASSIFIER = _REPO_ROOT / ".github" / "scripts" / "classify-ci-changes.sh"
_TIMEOUT_SECONDS = 30


def _module_file(*, dotted: str) -> Path | None:
    base = _SRC_ROOT.joinpath(*dotted.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def _package_of(*, path: Path) -> list[str]:
    return list(path.relative_to(_SRC_ROOT).parts[:-1])


def _imported_modules(*, path: Path) -> Iterator[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    in_src = path.is_relative_to(_SRC_ROOT)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level and in_src:
                package = _package_of(path=path)
                anchor = package[: len(package) - node.level + 1]
                module = ".".join([*anchor, *([node.module] if node.module else [])])
            else:
                module = node.module or ""
            yield module
            yield from (f"{module}.{alias.name}" for alias in node.names)


def _closure(*, entry_points: list[Path]) -> set[Path]:
    seen: set[Path] = set()
    pending = list(entry_points)
    while pending:
        current = pending.pop()
        for dotted in _imported_modules(path=current):
            if dotted != "dev10x" and not dotted.startswith("dev10x."):
                continue
            parts = dotted.split(".")
            for depth in range(1, len(parts) + 1):
                found = _module_file(dotted=".".join(parts[:depth]))
                if found is not None and found not in seen:
                    seen.add(found)
                    pending.append(found)
    return seen


def _one_file_per_directory(*, files: set[Path]) -> list[str]:
    by_directory: dict[Path, Path] = {}
    for file in sorted(files):
        by_directory.setdefault(file.parent, file)
    return sorted(str(file.relative_to(_REPO_ROOT)) for file in by_directory.values())


_HOOK_ENTRY_POINTS = sorted((_REPO_ROOT / "hooks" / "scripts").glob("*.py"))
_SERVER_ENTRY_POINTS = sorted((_REPO_ROOT / "servers").glob("*.py"))
_HOOK_CLOSURE = _closure(entry_points=_HOOK_ENTRY_POINTS)
_SERVER_CLOSURE = _closure(entry_points=_SERVER_ENTRY_POINTS)


def _git(*args: str, cwd: Path) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
    )
    return completed.stdout.strip()


@pytest.fixture
def classify(tmp_path: Path) -> Callable[..., dict[str, str]]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "--quiet", cwd=repo)
    _git("config", "user.email", "ci@example.invalid", cwd=repo)
    _git("config", "user.name", "ci", cwd=repo)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git("add", "README.md", cwd=repo)
    _git("commit", "--quiet", "-m", "base", cwd=repo)
    base_sha = _git("rev-parse", "HEAD", cwd=repo)

    def run(*, changed: str) -> dict[str, str]:
        target = repo / changed
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("changed\n", encoding="utf-8")
        _git("add", changed, cwd=repo)
        _git("commit", "--quiet", "-m", f"change {changed}", cwd=repo)
        output = tmp_path / "github_output"
        subprocess.run(
            [str(_CLASSIFIER)],
            cwd=repo,
            check=True,
            capture_output=True,
            env={
                "PATH": "/usr/bin:/bin",
                "GITHUB_EVENT_NAME": "pull_request",
                "GITHUB_OUTPUT": str(output),
                "BASE_SHA": base_sha,
                "HEAD_SHA": _git("rev-parse", "HEAD", cwd=repo),
            },
            timeout=_TIMEOUT_SECONDS,
        )
        pairs = output.read_text(encoding="utf-8").splitlines()
        return dict(pair.split("=", 1) for pair in pairs)

    return run


class TestImportClosureIsReal:
    def test_hook_closure_reaches_core(self) -> None:
        """Guards the walker itself: an empty closure would pass vacuously."""
        assert _SRC_ROOT / "dev10x" / "commands" / "hook.py" in _HOOK_CLOSURE
        assert any("core" in file.relative_to(_SRC_ROOT).parts for file in _HOOK_CLOSURE)

    def test_server_closure_reaches_the_cli_server(self) -> None:
        assert _SRC_ROOT / "dev10x" / "mcp" / "server_cli.py" in _SERVER_CLOSURE


class TestHookTestsSelection:
    @pytest.mark.parametrize("changed", _one_file_per_directory(files=_HOOK_CLOSURE))
    def test_module_imported_by_a_hook_selects_hook_tests(
        self,
        classify,
        changed: str,
    ) -> None:
        assert classify(changed=changed)["hooks"] == "true"

    @pytest.mark.parametrize(
        "changed",
        [
            "src/dev10x/core/config/loader.py",
            "src/dev10x/core/skill_rename.py",
            "src/dev10x/commands/hook.py",
        ],
    )
    def test_modules_that_were_skipped_select_hook_tests(
        self,
        classify,
        changed: str,
    ) -> None:
        """The concrete misses from #1584, #1591, #1592 and #1593."""
        assert classify(changed=changed)["hooks"] == "true"


class TestServerTestsSelection:
    @pytest.mark.parametrize("changed", _one_file_per_directory(files=_SERVER_CLOSURE))
    def test_module_imported_by_a_server_selects_server_tests(
        self,
        classify,
        changed: str,
    ) -> None:
        assert classify(changed=changed)["servers"] == "true"


class TestUnrelatedChangesStayFiltered:
    @pytest.mark.parametrize("changed", ["docs/notes.md", "README.md", "skills/x/SKILL.md"])
    def test_non_code_change_skips_both_suites(self, classify, changed: str) -> None:
        outputs = classify(changed=changed)
        assert (outputs["hooks"], outputs["servers"]) == ("false", "false")
