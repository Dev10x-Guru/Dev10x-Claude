from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from dev10x.comm.skills.notifications.slack_review_request import SLACK_NOTIFY_SCRIPT
from dev10x.core.paths import skill_files, skill_roots, skill_script
from dev10x.core.validators.sql_safety import DB_SH_PATH
from dev10x.subprocess_utils import get_plugin_root

SCRIPT_LITERAL = re.compile(r"^skills/[A-Za-z0-9_-]+/scripts/")
RESOLVER = Path("core") / "paths.py"
IMPORT_PROBE_TIMEOUT_SECONDS = 30
IMPORT_PROBE = """
import importlib, json, sys
sys.path.insert(0, sys.argv[1])
before = set(sys.modules)
importlib.import_module(sys.argv[2])
loaded = {name.split(".")[0] for name in set(sys.modules) - before}
print(json.dumps(sorted(loaded - set(sys.stdlib_module_names) - {"dev10x"})))
"""


def _src_root() -> Path:
    return get_plugin_root() / "src" / "dev10x"


def script_literals(*, source: str) -> list[tuple[int, str]]:
    return [
        (node.lineno, node.value)
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and SCRIPT_LITERAL.match(node.value)
    ]


def non_stdlib_modules_loaded_by(*, module: str, src_root: Path) -> list[str]:
    completed = subprocess.run(
        [sys.executable, "-I", "-c", IMPORT_PROBE, str(src_root), module],
        capture_output=True,
        text=True,
        timeout=IMPORT_PROBE_TIMEOUT_SECONDS,
        check=True,
    )
    return json.loads(completed.stdout)


def test_skill_script_builds_the_plugin_relative_path() -> None:
    assert skill_script(skill="gh-context", rel="gh-pr-get.sh") == (
        "skills/gh-context/scripts/gh-pr-get.sh"
    )


def test_skill_script_builds_a_satellite_repo_path() -> None:
    assert skill_script(skill="tts", rel="synthesize.py", plugin="qa") == (
        "plugins/qa/skills/tts/scripts/synthesize.py"
    )


def test_src_resolves_scripts_through_the_resolver() -> None:
    offenders = [
        f"{path.relative_to(_src_root())}:{lineno} {value}"
        for path in sorted(_src_root().rglob("*.py"))
        if path.relative_to(_src_root()) != RESOLVER
        for lineno, value in script_literals(source=path.read_text())
    ]

    assert offenders == [], (
        "Use dev10x.core.paths.skill_script instead of a skills/<name>/scripts/ "
        "literal (GH-1526):\n  - " + "\n  - ".join(offenders)
    )


def resolved_script_calls(*, source: str) -> list[tuple[int, str]]:
    """Every ``skill_script(skill=..., rel=...)`` call made with literals."""
    calls = []
    for node in ast.walk(ast.parse(source)):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "skill_script"
        ):
            continue
        kwargs = {kw.arg: kw.value for kw in node.keywords}
        literals = [kwargs.get("skill"), kwargs.get("rel")]
        plugin = kwargs.get("plugin")
        if all(isinstance(value, ast.Constant) for value in literals):
            skill, rel = (value.value for value in literals)
            satellite = plugin.value if isinstance(plugin, ast.Constant) else None
            calls.append((node.lineno, skill_script(skill=skill, rel=rel, plugin=satellite)))
    return calls


def test_every_resolved_script_exists() -> None:
    """GH-1751: a path that does not exist in the package fails here, not
    in a session that needed the tool."""
    missing = [
        f"{path.relative_to(_src_root())}:{lineno} {script}"
        for path in sorted(_src_root().rglob("*.py"))
        for lineno, script in resolved_script_calls(source=path.read_text())
        if not (get_plugin_root() / script).is_file()
    ]

    assert missing == [], "skill_script() points at a missing file:\n  - " + "\n  - ".join(missing)


@pytest.mark.parametrize(
    "script",
    [
        pytest.param(SLACK_NOTIFY_SCRIPT, id="slack-notify"),
        pytest.param(DB_SH_PATH, id="db.sh"),
    ],
)
def test_hand_built_script_paths_exist(script: Path) -> None:
    """GH-1751: paths assembled outside skill_script() break the same way."""
    assert script.is_file()


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            'skill_script(skill="git", rel="git-push-safe.sh")\n',
            [(1, "skills/git/scripts/git-push-safe.sh")],
        ),
        ('skill_script(skill=name, rel="x.sh")\n', []),
        ('other(skill="git", rel="x.sh")\n', []),
    ],
)
def test_resolved_script_detector(source: str, expected: list[tuple[int, str]]) -> None:
    assert resolved_script_calls(source=source) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            'run("skills/git/scripts/git-push-safe.sh")\n',
            [(1, "skills/git/scripts/git-push-safe.sh")],
        ),
        ('note = "see skills/git/scripts/ in prose"\n', []),
        ('GLOB = "skills/*/scripts/*.py"\n', []),
    ],
)
def test_detector(source: str, expected: list[tuple[int, str]]) -> None:
    assert script_literals(source=source) == expected


class TestSkillRoots:
    def test_core_root_comes_first_then_satellites(self, split_repo: Path) -> None:
        assert skill_roots(repo_root=split_repo) == [
            split_repo / "skills",
            split_repo / "plugins" / "infra" / "skills",
            split_repo / "plugins" / "qa" / "skills",
        ]

    def test_a_repo_without_satellites_has_only_the_core_root(self, tmp_path: Path) -> None:
        assert skill_roots(repo_root=tmp_path) == [tmp_path / "skills"]

    def test_skill_files_span_every_root(self, split_repo: Path) -> None:
        assert [
            path.relative_to(split_repo).as_posix() for path in skill_files(repo_root=split_repo)
        ] == [
            "skills/afk/SKILL.md",
            "plugins/infra/skills/k8s/SKILL.md",
            "plugins/qa/skills/tts/SKILL.md",
        ]

    def test_importing_paths_loads_only_the_standard_library(self) -> None:
        loaded = non_stdlib_modules_loaded_by(
            module="dev10x.core.paths", src_root=_src_root().parent
        )

        assert loaded == []

    def test_the_probe_reports_a_third_party_import(self) -> None:
        loaded = non_stdlib_modules_loaded_by(
            module="dev10x.core.plugin_map", src_root=_src_root().parent
        )

        assert "yaml" in loaded
