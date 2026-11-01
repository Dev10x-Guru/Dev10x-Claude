"""render.sh for dev10x:diagram-bpmn lays out and renders BPMN without hand-written DI (GH-1637).

Three layers:

- the pure lane geometry, via its ``node --test`` suite;
- render.sh, with stub ``pnpm``/``node``/``bpmn-to-image`` binaries so
  every branch runs offline;
- layout.mjs against the real toolchain, only when it is already cached
  (CI never downloads it).
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "skills" / "diagram-bpmn" / "scripts"
SCRIPT = SCRIPTS / "render.sh"
LANES_TESTS = Path(__file__).with_name("lanes.test.mjs")
CACHED_DEPS = (
    Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "dev10x" / "diagram-bpmn"
)

STUB_PNPM = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$FAKE_DIR/pnpm_calls.txt"
if [[ -f "$FAKE_DIR/install_fails" ]]; then exit 1; fi
deps="$2"
mkdir -p "$deps/node_modules/.bin"
cat > "$deps/node_modules/.bin/bpmn-to-image" <<'EOF'
#!/usr/bin/env bash
printf '%s\\n' "${PUPPETEER_EXECUTABLE_PATH:-unset}" > "$FAKE_DIR/puppeteer_path.txt"
if [[ -f "$FAKE_DIR/render_fails" ]]; then exit 1; fi
if [[ -f "$FAKE_DIR/empty_output" ]]; then exit 0; fi
target="${@: -1}"
printf 'IMG' > "${target#*:}"
EOF
chmod +x "$deps/node_modules/.bin/bpmn-to-image"
"""

STUB_NODE = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$FAKE_DIR/node_calls.txt"
if [[ -f "$FAKE_DIR/layout_fails" ]]; then
  echo "ERROR: Task_X is in no lane; add it to one lane's flowNodeRef" >&2
  exit 1
fi
"""

SEMANTIC_BPMN = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  id="Definitions_1" targetNamespace="https://example.com/bpmn">
  <bpmn:process id="Process_1" isExecutable="false">
    <bpmn:startEvent id="Start_1" />
    <bpmn:userTask id="Task_1" name="Do it" />
    <bpmn:endEvent id="End_1" />
    <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1" />
    <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1" />
  </bpmn:process>
</bpmn:definitions>
"""


def _install(*, bin_dir: Path, name: str, body: str) -> Path:
    path = bin_dir / name
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


@pytest.fixture
def fake_dir(tmp_path: Path) -> Path:
    fake = tmp_path / "fake"
    fake.mkdir()
    return fake


@pytest.fixture
def bin_dir(tmp_path: Path) -> Path:
    stubs = tmp_path / "bin"
    stubs.mkdir()
    _install(bin_dir=stubs, name="pnpm", body=STUB_PNPM)
    _install(bin_dir=stubs, name="node", body=STUB_NODE)
    _install(bin_dir=stubs, name="google-chrome-stable", body="#!/bin/sh\n")
    return stubs


@pytest.fixture
def deps_dir(tmp_path: Path) -> Path:
    return tmp_path / "deps"


@pytest.fixture
def source(tmp_path: Path) -> Path:
    path = tmp_path / "process.bpmn"
    path.write_text(SEMANTIC_BPMN)
    return path


def _run(
    *,
    args: list[str],
    bin_dir: Path,
    fake_dir: Path,
    deps_dir: Path,
    path: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {key: value for key, value in os.environ.items() if key != "PUPPETEER_EXECUTABLE_PATH"}
    env.update(
        {
            "PATH": path or f"{bin_dir}:/usr/bin:/bin",
            "FAKE_DIR": str(fake_dir),
            "DEV10X_BPMN_DEPS": str(deps_dir),
            **(extra_env or {}),
        }
    )
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
class TestLaneGeometry:
    def test_node_suite_passes(self) -> None:
        result = subprocess.run(
            ["node", "--test", str(LANES_TESTS)],
            capture_output=True,
            text=True,
            timeout=60,
        )

        assert result.returncode == 0, result.stdout + result.stderr


class TestArguments:
    @pytest.mark.parametrize(
        ("args", "message"),
        [
            ([], "Usage"),
            (["x.bpmn", "--bogus"], "Usage"),
            (["missing.bpmn"], "not found"),
            (["diagram.xml"], "expected a .bpmn file"),
        ],
    )
    def test_bad_invocation_exits_2(
        self,
        args: list[str],
        message: str,
        bin_dir: Path,
        fake_dir: Path,
        deps_dir: Path,
    ) -> None:
        result = _run(args=args, bin_dir=bin_dir, fake_dir=fake_dir, deps_dir=deps_dir)

        assert (result.returncode, message in result.stderr) == (2, True)

    def test_unknown_format_exits_2(
        self,
        source: Path,
        bin_dir: Path,
        fake_dir: Path,
        deps_dir: Path,
    ) -> None:
        result = _run(
            args=[str(source), "--format", "gif"],
            bin_dir=bin_dir,
            fake_dir=fake_dir,
            deps_dir=deps_dir,
        )

        assert (result.returncode, "png or svg" in result.stderr) == (2, True)


class TestToolchain:
    def test_first_run_installs_the_pinned_toolchain(
        self,
        source: Path,
        bin_dir: Path,
        fake_dir: Path,
        deps_dir: Path,
    ) -> None:
        _run(args=[str(source)], bin_dir=bin_dir, fake_dir=fake_dir, deps_dir=deps_dir)

        assert (
            (deps_dir / "package.json").read_text(),
            (deps_dir / "pnpm-workspace.yaml").read_text(),
        ) == (
            (SCRIPTS / "package.json").read_text(),
            (SCRIPTS / "pnpm-workspace.yaml").read_text(),
        )

    def test_install_tolerates_the_caches_previous_lockfile(
        self,
        source: Path,
        bin_dir: Path,
        fake_dir: Path,
        deps_dir: Path,
    ) -> None:
        _run(args=[str(source)], bin_dir=bin_dir, fake_dir=fake_dir, deps_dir=deps_dir)

        assert "--no-frozen-lockfile" in (fake_dir / "pnpm_calls.txt").read_text()

    def test_second_run_reuses_the_cache(
        self,
        source: Path,
        bin_dir: Path,
        fake_dir: Path,
        deps_dir: Path,
    ) -> None:
        _run(args=[str(source)], bin_dir=bin_dir, fake_dir=fake_dir, deps_dir=deps_dir)
        _run(args=[str(source)], bin_dir=bin_dir, fake_dir=fake_dir, deps_dir=deps_dir)

        assert len((fake_dir / "pnpm_calls.txt").read_text().splitlines()) == 1

    def test_changed_pins_trigger_a_reinstall(
        self,
        source: Path,
        bin_dir: Path,
        fake_dir: Path,
        deps_dir: Path,
    ) -> None:
        _run(args=[str(source)], bin_dir=bin_dir, fake_dir=fake_dir, deps_dir=deps_dir)
        (deps_dir / "package.json").write_text("{}")

        _run(args=[str(source)], bin_dir=bin_dir, fake_dir=fake_dir, deps_dir=deps_dir)

        assert len((fake_dir / "pnpm_calls.txt").read_text().splitlines()) == 2

    def test_changed_install_policy_triggers_a_reinstall(
        self,
        source: Path,
        bin_dir: Path,
        fake_dir: Path,
        deps_dir: Path,
    ) -> None:
        _run(args=[str(source)], bin_dir=bin_dir, fake_dir=fake_dir, deps_dir=deps_dir)
        (deps_dir / "pnpm-workspace.yaml").write_text("allowBuilds: {}\n")

        _run(args=[str(source)], bin_dir=bin_dir, fake_dir=fake_dir, deps_dir=deps_dir)

        assert len((fake_dir / "pnpm_calls.txt").read_text().splitlines()) == 2

    def test_failed_reinstall_is_retried_on_the_next_run(
        self,
        source: Path,
        bin_dir: Path,
        fake_dir: Path,
        deps_dir: Path,
    ) -> None:
        _run(args=[str(source)], bin_dir=bin_dir, fake_dir=fake_dir, deps_dir=deps_dir)
        (deps_dir / "package.json").write_text("{}")
        (fake_dir / "install_fails").write_text("")
        _run(args=[str(source)], bin_dir=bin_dir, fake_dir=fake_dir, deps_dir=deps_dir)
        (fake_dir / "install_fails").unlink()

        _run(args=[str(source)], bin_dir=bin_dir, fake_dir=fake_dir, deps_dir=deps_dir)

        assert len((fake_dir / "pnpm_calls.txt").read_text().splitlines()) == 3

    def test_missing_cached_binary_triggers_a_reinstall(
        self,
        source: Path,
        bin_dir: Path,
        fake_dir: Path,
        deps_dir: Path,
    ) -> None:
        _run(args=[str(source)], bin_dir=bin_dir, fake_dir=fake_dir, deps_dir=deps_dir)
        (deps_dir / "node_modules" / ".bin" / "bpmn-to-image").unlink()

        _run(args=[str(source)], bin_dir=bin_dir, fake_dir=fake_dir, deps_dir=deps_dir)

        assert len((fake_dir / "pnpm_calls.txt").read_text().splitlines()) == 2

    def test_install_failure_exits_3(
        self,
        source: Path,
        bin_dir: Path,
        fake_dir: Path,
        deps_dir: Path,
    ) -> None:
        (fake_dir / "install_fails").write_text("")

        result = _run(args=[str(source)], bin_dir=bin_dir, fake_dir=fake_dir, deps_dir=deps_dir)

        assert (result.returncode, "could not install" in result.stderr) == (3, True)


class TestLayoutAndRender:
    def test_success_prints_the_image_path(
        self,
        source: Path,
        bin_dir: Path,
        fake_dir: Path,
        deps_dir: Path,
    ) -> None:
        result = _run(args=[str(source)], bin_dir=bin_dir, fake_dir=fake_dir, deps_dir=deps_dir)

        assert result.stdout == f"rendered: {source.with_suffix('.png')}\n"

    def test_svg_format_writes_an_svg(
        self,
        source: Path,
        bin_dir: Path,
        fake_dir: Path,
        deps_dir: Path,
    ) -> None:
        result = _run(
            args=[str(source), "--format", "svg"],
            bin_dir=bin_dir,
            fake_dir=fake_dir,
            deps_dir=deps_dir,
        )

        assert result.stdout == f"rendered: {source.with_suffix('.svg')}\n"

    def test_clean_exit_without_an_image_exits_4(
        self,
        source: Path,
        bin_dir: Path,
        fake_dir: Path,
        deps_dir: Path,
    ) -> None:
        (fake_dir / "empty_output").write_text("")

        result = _run(args=[str(source)], bin_dir=bin_dir, fake_dir=fake_dir, deps_dir=deps_dir)

        assert (result.returncode, "wrote no image" in result.stderr) == (4, True)

    def test_failed_render_removes_a_stale_image(
        self,
        source: Path,
        bin_dir: Path,
        fake_dir: Path,
        deps_dir: Path,
    ) -> None:
        source.with_suffix(".png").write_bytes(b"OLD")
        (fake_dir / "render_fails").write_text("")

        result = _run(args=[str(source)], bin_dir=bin_dir, fake_dir=fake_dir, deps_dir=deps_dir)

        assert (result.returncode, source.with_suffix(".png").exists()) == (1, False)

    def test_layout_gets_the_deps_dir_and_source(
        self,
        source: Path,
        bin_dir: Path,
        fake_dir: Path,
        deps_dir: Path,
    ) -> None:
        _run(args=[str(source)], bin_dir=bin_dir, fake_dir=fake_dir, deps_dir=deps_dir)

        assert (fake_dir / "node_calls.txt").read_text().strip() == (
            f"{SCRIPTS / 'layout.mjs'} {deps_dir} {source}"
        )

    def test_relayout_flag_is_forwarded(
        self,
        source: Path,
        bin_dir: Path,
        fake_dir: Path,
        deps_dir: Path,
    ) -> None:
        _run(
            args=[str(source), "--relayout"],
            bin_dir=bin_dir,
            fake_dir=fake_dir,
            deps_dir=deps_dir,
        )

        assert (fake_dir / "node_calls.txt").read_text().strip().endswith("--relayout")

    def test_layout_failure_stops_before_rendering(
        self,
        source: Path,
        bin_dir: Path,
        fake_dir: Path,
        deps_dir: Path,
    ) -> None:
        (fake_dir / "layout_fails").write_text("")

        result = _run(args=[str(source)], bin_dir=bin_dir, fake_dir=fake_dir, deps_dir=deps_dir)

        assert (result.returncode, source.with_suffix(".png").exists()) == (1, False)

    def test_system_chrome_is_handed_to_puppeteer(
        self,
        source: Path,
        bin_dir: Path,
        fake_dir: Path,
        deps_dir: Path,
    ) -> None:
        _run(args=[str(source)], bin_dir=bin_dir, fake_dir=fake_dir, deps_dir=deps_dir)

        assert (fake_dir / "puppeteer_path.txt").read_text().strip() == str(
            bin_dir / "google-chrome-stable"
        )

    def test_preset_puppeteer_path_is_kept(
        self,
        source: Path,
        bin_dir: Path,
        fake_dir: Path,
        deps_dir: Path,
    ) -> None:
        _run(
            args=[str(source)],
            bin_dir=bin_dir,
            fake_dir=fake_dir,
            deps_dir=deps_dir,
            extra_env={"PUPPETEER_EXECUTABLE_PATH": "/opt/chrome"},
        )

        assert (fake_dir / "puppeteer_path.txt").read_text().strip() == "/opt/chrome"

    def test_missing_node_exits_3_before_installing(
        self,
        tmp_path: Path,
        source: Path,
        fake_dir: Path,
        deps_dir: Path,
    ) -> None:
        minimal = tmp_path / "no-node-bin"
        minimal.mkdir()
        _install(bin_dir=minimal, name="pnpm", body=STUB_PNPM)
        for tool in ("bash", "dirname"):
            (minimal / tool).symlink_to(shutil.which(tool))

        result = _run(
            args=[str(source)],
            bin_dir=minimal,
            fake_dir=fake_dir,
            deps_dir=deps_dir,
            path=str(minimal),
        )

        assert (
            result.returncode,
            "'node' not found" in result.stderr,
            (fake_dir / "pnpm_calls.txt").exists(),
        ) == (3, True, False)

    def test_missing_chrome_exits_3_but_keeps_the_layout(
        self,
        tmp_path: Path,
        source: Path,
        fake_dir: Path,
        deps_dir: Path,
    ) -> None:
        minimal = tmp_path / "minimal-bin"
        minimal.mkdir()
        _install(bin_dir=minimal, name="pnpm", body=STUB_PNPM)
        _install(bin_dir=minimal, name="node", body=STUB_NODE)
        for tool in ("bash", "dirname", "cmp", "mkdir", "cp", "cat", "chmod", "rm"):
            (minimal / tool).symlink_to(shutil.which(tool))

        result = _run(
            args=[str(source)],
            bin_dir=minimal,
            fake_dir=fake_dir,
            deps_dir=deps_dir,
            path=str(minimal),
        )

        assert (
            result.returncode,
            "opens in Camunda Modeler" in result.stderr,
            (fake_dir / "node_calls.txt").exists(),
        ) == (3, True, True)


@pytest.mark.skipif(
    shutil.which("node") is None or not (CACHED_DEPS / "node_modules" / "bpmn-moddle").is_dir(),
    reason="BPMN toolchain not cached; run render.sh once to install it",
)
class TestRealLayout:
    def _layout(self, *, source: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["node", str(SCRIPTS / "layout.mjs"), str(CACHED_DEPS), str(source)],
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_semantic_process_gains_shapes_and_edges(self, source: Path) -> None:
        self._layout(source=source)

        laid_out = source.read_text()
        assert (laid_out.count("<bpmndi:BPMNShape"), laid_out.count("<bpmndi:BPMNEdge")) == (3, 2)

    def test_existing_layout_is_kept(self, source: Path) -> None:
        self._layout(source=source)
        first = source.read_text()

        result = self._layout(source=source)

        assert (source.read_text() == first, "kept existing layout" in result.stderr) == (
            True,
            True,
        )

    def test_unknown_element_is_reported(self, tmp_path: Path) -> None:
        source = tmp_path / "bad.bpmn"
        source.write_text(SEMANTIC_BPMN.replace("bpmn:userTask", "bpmn:userTaks"))

        result = self._layout(source=source)

        assert (result.returncode, "cannot be laid out" in result.stderr) == (1, True)

    def test_node_outside_every_lane_is_reported(self, tmp_path: Path) -> None:
        source = tmp_path / "lanes.bpmn"
        source.write_text(
            SEMANTIC_BPMN.replace(
                '<bpmn:process id="Process_1" isExecutable="false">',
                '<bpmn:collaboration id="C"><bpmn:participant id="P" processRef="Process_1" />'
                '</bpmn:collaboration><bpmn:process id="Process_1" isExecutable="false">'
                '<bpmn:laneSet id="LS"><bpmn:lane id="L"><bpmn:flowNodeRef>Start_1'
                "</bpmn:flowNodeRef><bpmn:flowNodeRef>End_1</bpmn:flowNodeRef></bpmn:lane>"
                "</bpmn:laneSet>",
            )
        )

        result = self._layout(source=source)

        assert (result.returncode, "Task_1 is in no lane" in result.stderr) == (1, True)

    def test_malformed_xml_is_reported_without_a_stack_trace(self, tmp_path: Path) -> None:
        source = tmp_path / "broken.bpmn"
        source.write_text("<bpmn:definitions xmlns:bpmn=")

        result = self._layout(source=source)

        assert (
            result.returncode,
            "cannot be laid out" in result.stderr,
            "    at " in result.stderr,
        ) == (1, True, False)

    def test_pool_without_flow_nodes_is_rejected(self, tmp_path: Path) -> None:
        source = tmp_path / "empty-pool.bpmn"
        source.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"'
            ' id="D" targetNamespace="https://example.com/bpmn">'
            '<bpmn:collaboration id="C"><bpmn:participant id="P" processRef="Process_1" />'
            '</bpmn:collaboration><bpmn:process id="Process_1" isExecutable="false" />'
            "</bpmn:definitions>"
        )

        result = self._layout(source=source)

        assert (result.returncode, "no flow nodes" in result.stderr) == (1, True)

    def test_existing_layout_does_not_bypass_the_pool_check(self, tmp_path: Path) -> None:
        source = tmp_path / "tuned.bpmn"
        source.write_text(
            SEMANTIC_BPMN.replace(
                'xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"',
                'xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" '
                'xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"',
            )
            .replace(
                '<bpmn:process id="Process_1" isExecutable="false">',
                '<bpmn:collaboration id="C">'
                '<bpmn:participant id="P1" processRef="Process_1" />'
                '<bpmn:participant id="P2" name="Customer" />'
                '</bpmn:collaboration><bpmn:process id="Process_1" isExecutable="false">',
            )
            .replace(
                "</bpmn:definitions>",
                '<bpmndi:BPMNDiagram id="D"><bpmndi:BPMNPlane id="PL" bpmnElement="C" />'
                "</bpmndi:BPMNDiagram></bpmn:definitions>",
            )
        )

        result = self._layout(source=source)

        assert (result.returncode, "single pool" in result.stderr) == (1, True)

    def test_lanes_without_a_pool_are_rejected(self, tmp_path: Path) -> None:
        source = tmp_path / "poolless.bpmn"
        source.write_text(
            SEMANTIC_BPMN.replace(
                '<bpmn:process id="Process_1" isExecutable="false">',
                '<bpmn:process id="Process_1" isExecutable="false">'
                '<bpmn:laneSet id="LS"><bpmn:lane id="L"><bpmn:flowNodeRef>Start_1'
                "</bpmn:flowNodeRef></bpmn:lane></bpmn:laneSet>",
            )
        )

        result = self._layout(source=source)

        assert (result.returncode, "lanes need a pool" in result.stderr) == (1, True)

    def test_every_model_problem_is_reported_in_one_run(self, tmp_path: Path) -> None:
        source = tmp_path / "many-problems.bpmn"
        source.write_text(
            SEMANTIC_BPMN.replace(
                '<bpmn:process id="Process_1" isExecutable="false">',
                '<bpmn:process id="Process_1" isExecutable="false">'
                '<bpmn:laneSet id="LS"><bpmn:lane id="L"><bpmn:flowNodeRef>Start_1'
                "</bpmn:flowNodeRef></bpmn:lane></bpmn:laneSet>",
            )
        )

        result = self._layout(source=source)

        assert (
            result.returncode,
            "lanes need a pool" in result.stderr,
            "Task_1 is in no lane" in result.stderr,
            "3 problem(s)" in result.stderr,
        ) == (1, True, True, True)

    def test_second_pool_is_rejected(self, tmp_path: Path) -> None:
        source = tmp_path / "pools.bpmn"
        source.write_text(
            SEMANTIC_BPMN.replace(
                '<bpmn:process id="Process_1" isExecutable="false">',
                '<bpmn:collaboration id="C">'
                '<bpmn:participant id="P1" processRef="Process_1" />'
                '<bpmn:participant id="P2" name="Customer" />'
                '</bpmn:collaboration><bpmn:process id="Process_1" isExecutable="false">',
            )
        )

        result = self._layout(source=source)

        assert (result.returncode, "single pool" in result.stderr) == (1, True)

    def test_single_pool_gets_pool_and_lane_shapes(self, tmp_path: Path) -> None:
        source = tmp_path / "lanes.bpmn"
        source.write_text(
            SEMANTIC_BPMN.replace(
                '<bpmn:process id="Process_1" isExecutable="false">',
                '<bpmn:collaboration id="C"><bpmn:participant id="P" processRef="Process_1" />'
                '</bpmn:collaboration><bpmn:process id="Process_1" isExecutable="false">'
                '<bpmn:laneSet id="LS"><bpmn:lane id="L1"><bpmn:flowNodeRef>Start_1'
                "</bpmn:flowNodeRef><bpmn:flowNodeRef>Task_1</bpmn:flowNodeRef></bpmn:lane>"
                '<bpmn:lane id="L2"><bpmn:flowNodeRef>End_1</bpmn:flowNodeRef></bpmn:lane>'
                "</bpmn:laneSet>",
            )
        )

        self._layout(source=source)

        laid_out = source.read_text()
        assert all(f'bpmnElement="{element}"' in laid_out for element in ("C", "P", "L1", "L2"))
