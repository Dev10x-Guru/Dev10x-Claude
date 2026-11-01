"""render.sh for dev10x:diagram-sequence never reports a broken diagram as done (GH-1635).

Stub ``java``/``pnpm``/``google-chrome`` binaries go first on ``PATH`` so
each branch runs without the real toolchains; one class renders through
the real bundled PlantUML jar when ``java`` is installed.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "skills" / "diagram-sequence" / "scripts" / "render.sh"

STUB_JAVA = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$FAKE_DIR/java_calls.txt"
case " $* " in
  *" -syntax "*)
    if [[ -f "$FAKE_DIR/java_crashes" ]]; then exit 1; fi
    cat "$FAKE_DIR/syntax_report.txt" ;;
  *" -pipe "*)
    if [[ -f "$FAKE_DIR/render_fails" ]]; then exit 200; fi
    if [[ -f "$FAKE_DIR/empty_output" ]]; then exit 0; fi
    printf 'IMG' ;;
esac
"""

STUB_PNPM = """#!/usr/bin/env bash
printf '%s\\n' "${PUPPETEER_EXECUTABLE_PATH:-unset}" > "$FAKE_DIR/puppeteer_path.txt"
if [[ -f "$FAKE_DIR/mermaid_fails" ]]; then
  echo "Error: Parse error on line 8:" >&2
  echo "    at Parser.parseError (mermaid.mjs:409:21)" >&2
  exit 1
fi
while [[ $# -gt 0 ]]; do
  if [[ "$1" == "--output" && ! -f "$FAKE_DIR/empty_output" ]]; then printf 'IMG' > "$2"; fi
  shift
done
"""

VALID_SYNTAX = "SEQUENCE\n(3 participants)\n"
INVALID_SYNTAX = "ERROR\n2\nSyntax Error? (Assumed diagram type: sequence)\n"


def _install(*, bin_dir: Path, name: str, body: str) -> Path:
    path = bin_dir / name
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


@pytest.fixture
def fake_dir(tmp_path: Path) -> Path:
    fake = tmp_path / "fake"
    fake.mkdir()
    (fake / "syntax_report.txt").write_text(VALID_SYNTAX)
    return fake


@pytest.fixture
def bin_dir(tmp_path: Path) -> Path:
    stubs = tmp_path / "bin"
    stubs.mkdir()
    _install(bin_dir=stubs, name="java", body=STUB_JAVA)
    _install(bin_dir=stubs, name="pnpm", body=STUB_PNPM)
    return stubs


@pytest.fixture
def home_dir(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    return home


def _run(
    *,
    args: list[str],
    bin_dir: Path,
    fake_dir: Path,
    home_dir: Path,
    script: Path = SCRIPT,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PLANTUML_JAR", "PUPPETEER_EXECUTABLE_PATH"}
    }
    env.update(
        {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "FAKE_DIR": str(fake_dir),
            "HOME": str(home_dir),
            **(extra_env or {}),
        }
    )
    return subprocess.run(
        ["bash", str(script), *args],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


@pytest.fixture
def puml(tmp_path: Path) -> Path:
    source = tmp_path / "flow.puml"
    source.write_text("@startuml named-differently\nA -> B : hi\n@enduml\n")
    return source


@pytest.fixture
def mmd(tmp_path: Path) -> Path:
    source = tmp_path / "flow.mmd"
    source.write_text("sequenceDiagram\n    A->>B: hi\n")
    return source


class TestArguments:
    @pytest.mark.parametrize(
        ("args", "message"),
        [
            ([], "Usage"),
            (["flow.puml", "--bogus"], "Usage"),
            (["missing.puml"], "source file not found"),
        ],
    )
    def test_bad_invocation_exits_2(
        self,
        args: list[str],
        message: str,
        bin_dir: Path,
        fake_dir: Path,
        home_dir: Path,
    ) -> None:
        result = _run(args=args, bin_dir=bin_dir, fake_dir=fake_dir, home_dir=home_dir)

        assert (result.returncode, message in result.stderr) == (2, True)

    def test_unknown_format_exits_2(
        self,
        puml: Path,
        bin_dir: Path,
        fake_dir: Path,
        home_dir: Path,
    ) -> None:
        result = _run(
            args=[str(puml), "--format", "gif"],
            bin_dir=bin_dir,
            fake_dir=fake_dir,
            home_dir=home_dir,
        )

        assert (result.returncode, "png or svg" in result.stderr) == (2, True)

    def test_unsupported_extension_exits_2(
        self,
        tmp_path: Path,
        bin_dir: Path,
        fake_dir: Path,
        home_dir: Path,
    ) -> None:
        source = tmp_path / "flow.txt"
        source.write_text("A -> B")

        result = _run(
            args=[str(source)],
            bin_dir=bin_dir,
            fake_dir=fake_dir,
            home_dir=home_dir,
        )

        assert (result.returncode, "unsupported extension" in result.stderr) == (2, True)


class TestPlantUml:
    def test_output_is_named_after_the_source_not_the_diagram(
        self,
        puml: Path,
        bin_dir: Path,
        fake_dir: Path,
        home_dir: Path,
    ) -> None:
        result = _run(args=[str(puml)], bin_dir=bin_dir, fake_dir=fake_dir, home_dir=home_dir)

        assert result.stdout == f"rendered: {puml.with_suffix('.png')}\n"

    def test_svg_format_is_passed_to_plantuml(
        self,
        puml: Path,
        bin_dir: Path,
        fake_dir: Path,
        home_dir: Path,
    ) -> None:
        _run(
            args=[str(puml), "--format", "svg"],
            bin_dir=bin_dir,
            fake_dir=fake_dir,
            home_dir=home_dir,
        )

        assert "-tsvg" in (fake_dir / "java_calls.txt").read_text()

    def test_plantuml_jar_env_wins(
        self,
        puml: Path,
        tmp_path: Path,
        bin_dir: Path,
        fake_dir: Path,
        home_dir: Path,
    ) -> None:
        jar = tmp_path / "custom.jar"
        jar.write_text("")

        _run(
            args=[str(puml)],
            bin_dir=bin_dir,
            fake_dir=fake_dir,
            home_dir=home_dir,
            extra_env={"PLANTUML_JAR": str(jar)},
        )

        assert f"-jar {jar}" in (fake_dir / "java_calls.txt").read_text()

    def test_syntax_error_names_the_one_based_line(
        self,
        puml: Path,
        bin_dir: Path,
        fake_dir: Path,
        home_dir: Path,
    ) -> None:
        (fake_dir / "syntax_report.txt").write_text(INVALID_SYNTAX)

        result = _run(args=[str(puml)], bin_dir=bin_dir, fake_dir=fake_dir, home_dir=home_dir)

        assert (result.returncode, "syntax error at line 3" in result.stderr) == (1, True)

    def test_syntax_error_writes_no_image(
        self,
        puml: Path,
        bin_dir: Path,
        fake_dir: Path,
        home_dir: Path,
    ) -> None:
        (fake_dir / "syntax_report.txt").write_text(INVALID_SYNTAX)

        result = _run(args=[str(puml)], bin_dir=bin_dir, fake_dir=fake_dir, home_dir=home_dir)

        assert (result.returncode, puml.with_suffix(".png").exists()) == (1, False)

    def test_crashed_syntax_check_exits_3_without_rendering(
        self,
        puml: Path,
        bin_dir: Path,
        fake_dir: Path,
        home_dir: Path,
    ) -> None:
        (fake_dir / "java_crashes").write_text("")

        result = _run(args=[str(puml)], bin_dir=bin_dir, fake_dir=fake_dir, home_dir=home_dir)

        assert (
            result.returncode,
            "could not run" in result.stderr,
            puml.with_suffix(".png").exists(),
        ) == (3, True, False)

    def test_missing_java_exits_3(
        self,
        tmp_path: Path,
        puml: Path,
        fake_dir: Path,
        home_dir: Path,
    ) -> None:
        minimal = tmp_path / "no-java-bin"
        minimal.mkdir()
        for tool in ("bash", "dirname", "rm"):
            (minimal / tool).symlink_to(shutil.which(tool))
        jar = tmp_path / "plantuml.jar"
        jar.write_text("")

        result = _run(
            args=[str(puml)],
            bin_dir=minimal,
            fake_dir=fake_dir,
            home_dir=home_dir,
            extra_env={"PATH": str(minimal), "PLANTUML_JAR": str(jar)},
        )

        assert (result.returncode, "'java' not found" in result.stderr) == (3, True)

    def test_syntax_error_removes_a_stale_image(
        self,
        puml: Path,
        bin_dir: Path,
        fake_dir: Path,
        home_dir: Path,
    ) -> None:
        puml.with_suffix(".png").write_bytes(b"OLD")
        (fake_dir / "syntax_report.txt").write_text(INVALID_SYNTAX)

        result = _run(args=[str(puml)], bin_dir=bin_dir, fake_dir=fake_dir, home_dir=home_dir)

        assert (result.returncode, puml.with_suffix(".png").exists()) == (1, False)

    def test_render_failure_removes_the_partial_image(
        self,
        puml: Path,
        bin_dir: Path,
        fake_dir: Path,
        home_dir: Path,
    ) -> None:
        (fake_dir / "render_fails").write_text("")

        result = _run(args=[str(puml)], bin_dir=bin_dir, fake_dir=fake_dir, home_dir=home_dir)

        assert (result.returncode, puml.with_suffix(".png").exists()) == (1, False)


class TestEmptyOutput:
    @pytest.mark.parametrize(
        ("name", "body"),
        [
            ("flow.puml", "@startuml\nA -> B : hi\n@enduml\n"),
            ("flow.mmd", "sequenceDiagram\n    A->>B: hi\n"),
        ],
    )
    def test_clean_exit_without_an_image_exits_4(
        self,
        name: str,
        body: str,
        tmp_path: Path,
        bin_dir: Path,
        fake_dir: Path,
        home_dir: Path,
    ) -> None:
        source = tmp_path / name
        source.write_text(body)
        (fake_dir / "empty_output").write_text("")

        result = _run(args=[str(source)], bin_dir=bin_dir, fake_dir=fake_dir, home_dir=home_dir)

        assert (result.returncode, "wrote no image" in result.stderr, result.stdout) == (
            4,
            True,
            "",
        )


class TestMissingJar:
    @pytest.fixture
    def isolated_script(self, tmp_path: Path) -> Path:
        scripts = tmp_path / "plugin" / "skills" / "diagram-sequence" / "scripts"
        scripts.mkdir(parents=True)
        copy = scripts / "render.sh"
        shutil.copy(SCRIPT, copy)
        shutil.copy(SCRIPT.with_name("_chrome.sh"), scripts / "_chrome.sh")
        return copy

    def test_no_jar_anywhere_exits_3(
        self,
        isolated_script: Path,
        puml: Path,
        bin_dir: Path,
        fake_dir: Path,
        home_dir: Path,
    ) -> None:
        result = _run(
            args=[str(puml)],
            bin_dir=bin_dir,
            fake_dir=fake_dir,
            home_dir=home_dir,
            script=isolated_script,
        )

        assert (result.returncode, "PLANTUML_JAR" in result.stderr) == (3, True)

    def test_home_jar_is_the_last_fallback(
        self,
        isolated_script: Path,
        puml: Path,
        bin_dir: Path,
        fake_dir: Path,
        home_dir: Path,
    ) -> None:
        jar = home_dir / ".local" / "bin" / "plantuml.jar"
        jar.parent.mkdir(parents=True)
        jar.write_text("")

        _run(
            args=[str(puml)],
            bin_dir=bin_dir,
            fake_dir=fake_dir,
            home_dir=home_dir,
            script=isolated_script,
        )

        assert f"-jar {jar}" in (fake_dir / "java_calls.txt").read_text()


class TestMermaid:
    def test_success_prints_the_image_path(
        self,
        mmd: Path,
        bin_dir: Path,
        fake_dir: Path,
        home_dir: Path,
    ) -> None:
        result = _run(args=[str(mmd)], bin_dir=bin_dir, fake_dir=fake_dir, home_dir=home_dir)

        assert result.stdout == f"rendered: {mmd.with_suffix('.png')}\n"

    def test_system_chrome_is_handed_to_puppeteer(
        self,
        mmd: Path,
        bin_dir: Path,
        fake_dir: Path,
        home_dir: Path,
    ) -> None:
        chrome = _install(bin_dir=bin_dir, name="google-chrome-stable", body="#!/bin/sh\n")

        _run(args=[str(mmd)], bin_dir=bin_dir, fake_dir=fake_dir, home_dir=home_dir)

        assert (fake_dir / "puppeteer_path.txt").read_text().strip() == str(chrome)

    def test_preset_puppeteer_path_is_kept(
        self,
        mmd: Path,
        bin_dir: Path,
        fake_dir: Path,
        home_dir: Path,
    ) -> None:
        _install(bin_dir=bin_dir, name="google-chrome-stable", body="#!/bin/sh\n")

        _run(
            args=[str(mmd)],
            bin_dir=bin_dir,
            fake_dir=fake_dir,
            home_dir=home_dir,
            extra_env={"PUPPETEER_EXECUTABLE_PATH": "/opt/chrome"},
        )

        assert (fake_dir / "puppeteer_path.txt").read_text().strip() == "/opt/chrome"

    def test_parse_error_removes_a_stale_image(
        self,
        mmd: Path,
        bin_dir: Path,
        fake_dir: Path,
        home_dir: Path,
    ) -> None:
        mmd.with_suffix(".png").write_bytes(b"OLD")
        (fake_dir / "mermaid_fails").write_text("")

        result = _run(args=[str(mmd)], bin_dir=bin_dir, fake_dir=fake_dir, home_dir=home_dir)

        assert (result.returncode, mmd.with_suffix(".png").exists()) == (1, False)

    def test_unsupported_extension_leaves_same_named_images_alone(
        self,
        tmp_path: Path,
        bin_dir: Path,
        fake_dir: Path,
        home_dir: Path,
    ) -> None:
        source = tmp_path / "notes.txt"
        source.write_text("A -> B")
        unrelated = tmp_path / "notes.png"
        unrelated.write_bytes(b"KEEP")

        _run(args=[str(source)], bin_dir=bin_dir, fake_dir=fake_dir, home_dir=home_dir)

        assert unrelated.read_bytes() == b"KEEP"

    def test_parse_error_fails_without_stack_frames(
        self,
        mmd: Path,
        bin_dir: Path,
        fake_dir: Path,
        home_dir: Path,
    ) -> None:
        (fake_dir / "mermaid_fails").write_text("")

        result = _run(args=[str(mmd)], bin_dir=bin_dir, fake_dir=fake_dir, home_dir=home_dir)

        assert (
            result.returncode,
            "Parse error on line 8" in result.stderr,
            "    at " in result.stderr,
        ) == (1, True, False)


@pytest.mark.skipif(shutil.which("java") is None, reason="java not installed")
class TestRealPlantUml:
    @pytest.fixture
    def real_env(self, tmp_path: Path) -> dict[str, str]:
        return {
            **{key: value for key, value in os.environ.items() if key != "PLANTUML_JAR"},
            "HOME": str(tmp_path),
        }

    def test_valid_source_renders_a_png(self, puml: Path, real_env: dict[str, str]) -> None:
        result = subprocess.run(
            ["bash", str(SCRIPT), str(puml)],
            capture_output=True,
            text=True,
            timeout=120,
            env=real_env,
        )

        assert (result.returncode, puml.with_suffix(".png").read_bytes()[:4]) == (
            0,
            b"\x89PNG",
        )

    def test_invalid_line_is_reported(
        self,
        tmp_path: Path,
        real_env: dict[str, str],
    ) -> None:
        source = tmp_path / "broken.puml"
        source.write_text("@startuml\nA -> B : hi\nthis line is not plantuml\n@enduml\n")

        result = subprocess.run(
            ["bash", str(SCRIPT), str(source)],
            capture_output=True,
            text=True,
            timeout=120,
            env=real_env,
        )

        assert (result.returncode, "syntax error at line 3" in result.stderr) == (1, True)
