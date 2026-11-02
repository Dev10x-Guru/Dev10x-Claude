"""Every skill renders PlantUML through the sandboxed render script (GH-1797).

`skills/diagram-sequence/scripts/render.sh` runs the jar under the SANDBOX
security profile; a skill doc that tells the agent to call `java -jar` on
a PlantUML jar directly bypasses it, and `Bash(java -jar:*)` in
`allowed-tools` pre-approves exactly that bypass.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
RENDER_SCRIPT = REPO_ROOT / "skills" / "diagram-sequence" / "scripts" / "render.sh"
RENDER_GRANT = "Bash(${CLAUDE_PLUGIN_ROOT}/skills/diagram-sequence/scripts/render.sh:*)"
SKILL_DOCS = sorted(
    [*REPO_ROOT.glob("skills/**/*.md"), *REPO_ROOT.glob("plugins/*/skills/**/*.md")]
)
PERMISSION_CATALOGS = sorted(REPO_ROOT.glob("src/dev10x/**/permission/*.yaml"))
DIRECT_JAR_CALL = re.compile(r"java\s+(?:-\S+\s+)*-jar\s+\S*plantuml\S*\.jar", re.IGNORECASE)
BROAD_JAVA_GRANT = re.compile(re.escape("Bash(java -jar:*)"))


def _offending_lines(*, files: list[Path], pattern: re.Pattern[str]) -> list[str]:
    return [
        f"{path.relative_to(REPO_ROOT)}:{number}: {line.strip()}"
        for path in files
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if pattern.search(line)
    ]


def _allowed_tools(*, skill: str) -> list[str]:
    text = (REPO_ROOT / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
    front_matter = yaml.safe_load(text.split("---", maxsplit=2)[1])
    return front_matter["allowed-tools"]


class TestPlantUmlRendersAreSandboxed:
    def test_skill_docs_and_catalogs_were_found(self) -> None:
        assert (len(SKILL_DOCS) > 20, len(PERMISSION_CATALOGS) > 0) == (True, True)

    def test_no_skill_doc_calls_the_plantuml_jar_directly(self) -> None:
        assert _offending_lines(files=SKILL_DOCS, pattern=DIRECT_JAR_CALL) == []

    def test_no_skill_pre_approves_arbitrary_jars(self) -> None:
        assert _offending_lines(files=SKILL_DOCS, pattern=BROAD_JAVA_GRANT) == []

    def test_no_permission_catalog_seeds_a_direct_plantuml_render(self) -> None:
        assert _offending_lines(files=PERMISSION_CATALOGS, pattern=DIRECT_JAR_CALL) == []

    @pytest.mark.parametrize("skill", ["scope", "adr", "ticket-scope"])
    def test_skill_declares_the_render_script(self, skill: str) -> None:
        assert RENDER_GRANT in _allowed_tools(skill=skill)

    def test_render_script_still_defaults_to_sandbox(self) -> None:
        assert 'SECURITY_PROFILE="${PLANTUML_SECURITY_PROFILE:-SANDBOX}"' in (
            RENDER_SCRIPT.read_text(encoding="utf-8")
        )
