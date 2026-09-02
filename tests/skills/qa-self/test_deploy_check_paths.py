"""The qa-self deploy check stays deployment-agnostic (GH-1147).

Phase 1.2 once hardcoded absolute clone paths and the argocd manifest
path, so the step the skill itself calls "critical" was unrunnable
outside one deployment — and therefore the first step to get skipped.
GH-1130 fixed the same class of defect in ``run-playwright.sh``; these
tests pin the documentation half so it cannot drift back.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_INSTRUCTIONS = _REPO_ROOT / "skills" / "qa-self" / "instructions.md"

_KNOBS = (
    "QA_ARGOCD_REPO",
    "QA_APP_REPO",
    "QA_STAGING_MANIFEST",
    "QA_FRONTEND_REPO",
)

# The only deployment-specific paths the skill may still name, and only
# as the fallback half of an override. A path absent from this set is a
# new hardcoding; a path present but no longer in the file means the
# knob it documented went away.
_EXPECTED_DEFAULT_PATHS = {
    "/work/example/app-argocd",
    "/work/example/app-pos",
    "/work/example/app-admin",
    "/work/example/app-e2e/settings.secrets.env",
}


@pytest.fixture(scope="module")
def instructions() -> str:
    return _INSTRUCTIONS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def deployment_path_lines(instructions: str) -> list[str]:
    return [line for line in instructions.splitlines() if "/work/example/" in line]


@pytest.fixture(scope="module")
def manifest_lines(instructions: str) -> list[str]:
    return [line for line in instructions.splitlines() if "apps/staging/" in line]


class TestKnobsAreDocumented:
    @pytest.mark.parametrize("knob", _KNOBS)
    def test_knob_is_named(self, instructions: str, knob: str):
        assert knob in instructions

    @pytest.mark.parametrize("knob", _KNOBS)
    def test_knob_declares_a_default(self, instructions: str, knob: str):
        assert re.search(rf"\$\{{{knob}:-[^}}]+\}}", instructions)


class TestNoBakedInPaths:
    def test_no_git_command_names_an_absolute_deployment_path(self, instructions: str):
        assert not re.search(r"git -C\s+/work/", instructions)

    def test_manifest_path_only_appears_as_a_default(self, manifest_lines: list[str]):
        assert manifest_lines, "the manifest default vanished — the knob is undocumented"
        assert all("QA_STAGING_MANIFEST" in line for line in manifest_lines)

    def test_every_deployment_path_is_a_documented_default(self, deployment_path_lines: list[str]):
        # A path survives only as the fallback half of a `${VAR:-…}`
        # expansion, or on prose that names it as a default.
        for line in deployment_path_lines:
            assert ":-" in line or "default" in line.lower(), line

    def test_the_paths_that_remain_are_the_expected_ones(self, instructions: str):
        # Pins the identities rather than a count, so a stray new path
        # fails while unrelated prose edits do not.
        found = set(re.findall(r"/work/example/[\w./-]+", instructions))
        assert found == _EXPECTED_DEFAULT_PATHS
