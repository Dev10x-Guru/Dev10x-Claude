"""render.sh for dev10x:diagram-c4 catches C4 mistakes before PlantUML runs (GH-1636).

The wrapper owns three C4-specific checks and delegates the render to
dev10x:diagram-sequence's render.sh; a stub ``java`` stands in for
PlantUML, and one class renders through the real jar when ``java`` and
Graphviz are installed.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "skills" / "diagram-c4" / "scripts" / "render.sh"

STUB_JAVA = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$FAKE_DIR/java_calls.txt"
case " $* " in
  *" -syntax "*) printf 'DESCRIPTION\\n' ;;
  *" -pipe "*) printf 'IMG' ;;
esac
"""

VALID_C4 = """@startuml
!include <C4/C4_Context>
Person(dev, "Developer")
System(dx, "Dev10x")
Rel(dev, dx, "Uses")
SHOW_LEGEND()
@enduml
"""


def _install(*, bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@pytest.fixture
def fake_dir(tmp_path: Path) -> Path:
    fake = tmp_path / "fake"
    fake.mkdir()
    return fake


@pytest.fixture
def bin_dir(tmp_path: Path) -> Path:
    stubs = tmp_path / "bin"
    stubs.mkdir()
    _install(bin_dir=stubs, name="java", body=STUB_JAVA)
    _install(bin_dir=stubs, name="dot", body="#!/bin/sh\n")
    return stubs


def _run(
    *,
    args: list[str],
    path: str,
    fake_dir: Path,
) -> subprocess.CompletedProcess[str]:
    env = {key: value for key, value in os.environ.items() if key != "PLANTUML_JAR"}
    env.update({"PATH": path, "FAKE_DIR": str(fake_dir)})
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


@pytest.fixture
def stub_path(bin_dir: Path) -> str:
    return f"{bin_dir}:/usr/bin:/bin"


def _source(*, tmp_path: Path, body: str, name: str = "view.puml") -> Path:
    source = tmp_path / name
    source.write_text(body)
    return source


class TestArguments:
    def test_no_source_exits_2(self, stub_path: str, fake_dir: Path) -> None:
        result = _run(args=[], path=stub_path, fake_dir=fake_dir)

        assert (result.returncode, "Usage" in result.stderr) == (2, True)

    def test_mermaid_source_is_rejected(
        self,
        tmp_path: Path,
        stub_path: str,
        fake_dir: Path,
    ) -> None:
        source = _source(tmp_path=tmp_path, body="graph LR", name="view.mmd")

        result = _run(args=[str(source)], path=stub_path, fake_dir=fake_dir)

        assert (result.returncode, "use a .puml file" in result.stderr) == (2, True)

    def test_missing_file_exits_2(self, tmp_path: Path, stub_path: str, fake_dir: Path) -> None:
        result = _run(args=[str(tmp_path / "nope.puml")], path=stub_path, fake_dir=fake_dir)

        assert (result.returncode, "not found" in result.stderr) == (2, True)


class TestC4Checks:
    @pytest.mark.parametrize(
        "include",
        [
            "!include https://raw.githubusercontent.com/plantuml-stdlib/C4-PlantUML/master/C4_Container.puml",
            "!includeurl https://example.com/C4_Container.puml",
        ],
    )
    def test_network_include_is_rejected(
        self,
        include: str,
        tmp_path: Path,
        stub_path: str,
        fake_dir: Path,
    ) -> None:
        source = _source(tmp_path=tmp_path, body=f"@startuml\n{include}\n@enduml\n")

        result = _run(args=[str(source)], path=stub_path, fake_dir=fake_dir)

        assert (result.returncode, "!include <C4/C4_Container>" in result.stderr) == (1, True)

    @pytest.mark.parametrize(
        "macro_line",
        [
            'Person(dev, "Developer")',
            'Container(api, "API", "Python", "Serves JSON")',
            'ContainerDb(db, "DB", "Postgres", "Rows")',
            'Rel_R(a, b, "Calls")',
            'Deployment_Node(n, "Node", "Linux") {',
        ],
    )
    def test_macro_without_include_is_rejected(
        self,
        macro_line: str,
        tmp_path: Path,
        stub_path: str,
        fake_dir: Path,
    ) -> None:
        source = _source(tmp_path=tmp_path, body=f"@startuml\n{macro_line}\n@enduml\n")

        result = _run(args=[str(source)], path=stub_path, fake_dir=fake_dir)

        assert (result.returncode, "no C4 include" in result.stderr) == (1, True)

    def test_local_vendored_include_is_accepted(
        self,
        tmp_path: Path,
        stub_path: str,
        fake_dir: Path,
    ) -> None:
        source = _source(
            tmp_path=tmp_path,
            body='@startuml\n!include ./vendor/C4_Container.puml\nPerson(dev, "Dev")\n@enduml\n',
        )

        result = _run(args=[str(source)], path=stub_path, fake_dir=fake_dir)

        assert result.stdout == f"rendered: {source.with_suffix('.png')}\n"

    def test_rejected_source_never_reaches_plantuml(
        self,
        tmp_path: Path,
        stub_path: str,
        fake_dir: Path,
    ) -> None:
        source = _source(tmp_path=tmp_path, body='@startuml\nPerson(dev, "Dev")\n@enduml\n')

        result = _run(args=[str(source)], path=stub_path, fake_dir=fake_dir)

        assert (result.returncode, (fake_dir / "java_calls.txt").exists()) == (1, False)

    def test_missing_graphviz_exits_3(self, tmp_path: Path, fake_dir: Path) -> None:
        minimal = tmp_path / "minimal-bin"
        minimal.mkdir()
        for tool in ("bash", "grep", "dirname"):
            (minimal / tool).symlink_to(shutil.which(tool))
        source = _source(tmp_path=tmp_path, body=VALID_C4)

        result = _run(args=[str(source)], path=str(minimal), fake_dir=fake_dir)

        assert (result.returncode, "graphviz" in result.stderr) == (3, True)


class TestDelegation:
    def test_valid_source_renders_through_the_plantuml_path(
        self,
        tmp_path: Path,
        stub_path: str,
        fake_dir: Path,
    ) -> None:
        source = _source(tmp_path=tmp_path, body=VALID_C4)

        result = _run(args=[str(source)], path=stub_path, fake_dir=fake_dir)

        assert result.stdout == f"rendered: {source.with_suffix('.png')}\n"

    def test_format_flag_is_forwarded(
        self, tmp_path: Path, stub_path: str, fake_dir: Path
    ) -> None:
        source = _source(tmp_path=tmp_path, body=VALID_C4)

        _run(args=[str(source), "--format", "svg"], path=stub_path, fake_dir=fake_dir)

        assert "-tsvg" in (fake_dir / "java_calls.txt").read_text()


@pytest.mark.skipif(
    shutil.which("java") is None or shutil.which("dot") is None,
    reason="java and graphviz are both required for a real C4 render",
)
class TestRealC4Render:
    def test_stdlib_include_renders_offline(self, tmp_path: Path) -> None:
        source = _source(tmp_path=tmp_path, body=VALID_C4)
        env = {
            **{key: value for key, value in os.environ.items() if key != "PLANTUML_JAR"},
            "HOME": str(tmp_path),
        }

        result = subprocess.run(
            ["bash", str(SCRIPT), str(source)],
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )

        assert (result.returncode, source.with_suffix(".png").read_bytes()[:4]) == (
            0,
            b"\x89PNG",
        )
