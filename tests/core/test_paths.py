from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from dev10x.comm.skills.notifications.slack_review_request import SLACK_NOTIFY_SCRIPT
from dev10x.core.db_script import DB_KEY, DB_PLUGIN_NAME, DB_SCRIPT_SKILL, db_script
from dev10x.core.paths import (
    PLUGIN_MANIFEST,
    latest_version,
    satellite_cache_dir,
    satellite_script,
    satellite_subdir,
    skill_files,
    skill_roots,
    skill_script,
    version_sort_key,
)
from dev10x.core.plugin_map import PluginMap, load_plugin_map
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


class TestSatelliteScript:
    """GH-1566: core reaches a script that moved to a satellite."""

    IN_CORE = "plugins/db/skills/db-psql/scripts/db.sh"

    @pytest.fixture
    def core_root(self, tmp_path: Path) -> Path:
        root = tmp_path / "cache" / "Dev10x-Guru" / "dev10x" / "0.114.0"
        root.mkdir(parents=True)
        return root

    @pytest.fixture
    def satellite_root(self, core_root: Path) -> Path:
        return core_root.parent.parent / "dev10x-db" / "0.114.0"

    @pytest.fixture
    def beside(self, satellite_root: Path) -> Path:
        script = satellite_root / "skills/db-psql/scripts/db.sh"
        self._write(path=script, text="")
        return script

    def _resolve(self, *, core_root: Path) -> str:
        return satellite_script(
            plugin_root=core_root,
            key="db",
            plugin_name="dev10x-db",
            skill="db-psql",
            rel="db.sh",
        )

    @staticmethod
    def _write(*, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def _write_manifest(self, *, satellite_root: Path, text: str) -> None:
        self._write(path=satellite_root / PLUGIN_MANIFEST, text=text)

    def test_prefers_the_copy_under_core(
        self,
        core_root: Path,
        satellite_root: Path,
        beside: Path,
    ) -> None:
        self._write(path=core_root / self.IN_CORE, text="")
        self._write_manifest(satellite_root=satellite_root, text='{"name": "dev10x-db"}')

        assert self._resolve(core_root=core_root) == self.IN_CORE

    def test_finds_the_satellite_installed_beside_core(
        self,
        core_root: Path,
        satellite_root: Path,
        beside: Path,
    ) -> None:
        self._write_manifest(satellite_root=satellite_root, text='{"name": "dev10x-db"}')

        assert self._resolve(core_root=core_root) == str(beside)

    @pytest.mark.parametrize(
        "manifest",
        [
            pytest.param('{"name": "someone-else"}', id="other-plugin"),
            pytest.param("not json", id="unreadable"),
            pytest.param('["dev10x-db"]', id="not-an-object"),
        ],
    )
    def test_ignores_a_sibling_whose_manifest_names_another_plugin(
        self,
        core_root: Path,
        satellite_root: Path,
        beside: Path,
        manifest: str,
    ) -> None:
        self._write_manifest(satellite_root=satellite_root, text=manifest)

        assert self._resolve(core_root=core_root) == self.IN_CORE

    def test_ignores_a_sibling_without_a_manifest(self, core_root: Path, beside: Path) -> None:
        assert self._resolve(core_root=core_root) == self.IN_CORE

    def test_names_the_in_core_path_when_nothing_is_installed(self, core_root: Path) -> None:
        assert self._resolve(core_root=core_root) == self.IN_CORE

    @pytest.mark.parametrize("version", ["0.113.0", "0.115.0"], ids=["lags-core", "leads-core"])
    def test_finds_a_satellite_at_its_own_newest_version(
        self,
        core_root: Path,
        version: str,
    ) -> None:
        satellite_root = core_root.parent.parent / "dev10x-db" / version
        self._write(path=core_root.parent.parent / "dev10x-db" / "0.112.0" / "x", text="")
        script = satellite_root / "skills/db-psql/scripts/db.sh"
        self._write(path=script, text="")
        self._write_manifest(satellite_root=satellite_root, text='{"name": "dev10x-db"}')

        assert self._resolve(core_root=core_root) == str(script)


class TestSatelliteLayout:
    """GH-1886: one owner for each satellite layout rule."""

    def test_satellite_subdir(self) -> None:
        assert satellite_subdir(key="qa") == "plugins/qa"

    def test_satellite_cache_dir_sits_beside_core(self, tmp_path: Path) -> None:
        core_cache = tmp_path / "cache" / "Dev10x-Guru" / "dev10x"

        assert satellite_cache_dir(core_cache_dir=core_cache, plugin_name="dev10x-qa") == (
            tmp_path / "cache" / "Dev10x-Guru" / "dev10x-qa"
        )

    @pytest.mark.parametrize(
        ("names", "expected"),
        [
            pytest.param(["0.9.0", "0.10.0", "0.2.1"], "0.10.0", id="numeric-not-lexical"),
            pytest.param(["dev", "0.1.0"], "0.1.0", id="non-numeric-sorts-first"),
            pytest.param([], None, id="empty"),
        ],
    )
    def test_latest_version(
        self,
        tmp_path: Path,
        names: list[str],
        expected: str | None,
    ) -> None:
        for name in names:
            (tmp_path / name).mkdir()

        assert latest_version(versions_dir=tmp_path) == expected

    def test_latest_version_of_a_missing_dir(self, tmp_path: Path) -> None:
        assert latest_version(versions_dir=tmp_path / "absent") is None

    @pytest.mark.parametrize(
        ("name", "expected"),
        [("1.2.3", (1, 2, 3)), ("1.2.rc1", (0,))],
    )
    def test_version_sort_key(
        self,
        name: str,
        expected: tuple[int, ...],
    ) -> None:
        assert version_sort_key(name) == expected


class TestDbScriptConstants:
    @pytest.fixture
    def plugin_map(self) -> PluginMap:
        return load_plugin_map()

    def test_names_the_shipped_db_plugin(self, plugin_map: PluginMap) -> None:
        assert DB_PLUGIN_NAME == plugin_map.plugin_name(key=DB_KEY)

    def test_the_script_skill_ships_with_the_db_plugin(self, plugin_map: PluginMap) -> None:
        assert DB_SCRIPT_SKILL in plugin_map.plugins[DB_KEY]


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
    "build_script",
    [
        pytest.param(lambda: SLACK_NOTIFY_SCRIPT, id="slack-notify"),
        pytest.param(
            lambda: get_plugin_root() / db_script(plugin_root=get_plugin_root()),
            id="db.sh",
        ),
    ],
)
def test_hand_built_script_paths_exist(build_script: Callable[[], Path]) -> None:
    """GH-1751: paths assembled outside skill_script() break the same way."""
    assert build_script().is_file()


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
