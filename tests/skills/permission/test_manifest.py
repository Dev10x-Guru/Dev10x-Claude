"""Tests for the source-derived two-axis permission manifest (GH-600)."""

from __future__ import annotations

from pathlib import Path

import click
import pytest

import dev10x.skills.permission as permission_pkg
from dev10x.cli import cli
from dev10x.skills.permission.enumerate_mcp import discover_mcp_tools, plugin_root
from dev10x.skills.permission.manifest import (
    Access,
    ManifestEntry,
    Sensitivity,
    Surface,
    build_manifest,
    classify_skill_access,
    discovered_surface_keys,
    find_manifest_drift,
    manifest_from_cli,
    manifest_from_mcp_tools,
    manifest_from_skills,
)

PLUGIN_SKILLS = plugin_root() / "skills"


@pytest.fixture
def cli_group() -> click.Group:
    @click.group()
    def root() -> None: ...

    @root.group()
    def permission() -> None: ...

    @permission.command(name="list-rules")
    def list_rules() -> None: ...  # read verb

    @permission.command(name="delete-rule")
    def delete_rule() -> None: ...  # write verb

    @permission.command()
    def frobnicate() -> None: ...  # no read/write verb → unknown

    @root.group()
    def hook() -> None: ...

    @hook.command(name="validate-bash")
    def validate_bash() -> None: ...  # internal — excluded

    return root


def _write_skill(skills_dir: Path, name: str, body: str) -> Path:
    skill_dir = skills_dir / name
    skill_dir.mkdir(parents=True)
    md = skill_dir / "SKILL.md"
    md.write_text(body)
    return md


class TestManifestEntry:
    def test_key_is_surface_and_name(self) -> None:
        entry = ManifestEntry(Surface.MCP, "mcp__x__get_y", Access.READ, Sensitivity.BENIGN)
        assert entry.key == ("mcp", "mcp__x__get_y")

    def test_benign_read_is_default_safe(self) -> None:
        entry = ManifestEntry(Surface.MCP, "mcp__x__get_y", Access.READ, Sensitivity.BENIGN)
        assert entry.default_safe is True

    @pytest.mark.parametrize(
        "access,sensitivity",
        [
            (Access.WRITE, Sensitivity.MUTATING),
            (Access.READ, Sensitivity.PII),
            (Access.READ, Sensitivity.SECRET),
            (Access.UNKNOWN, Sensitivity.BENIGN),
        ],
    )
    def test_non_benign_read_is_not_default_safe(
        self, access: Access, sensitivity: Sensitivity
    ) -> None:
        entry = ManifestEntry(Surface.MCP, "tool", access, sensitivity)
        assert entry.default_safe is False


class TestManifestFromMcpTools:
    def test_read_tool_is_benign(self) -> None:
        (entry,) = manifest_from_mcp_tools(["mcp__claude_ai_Sentry__search_issues"])
        assert (entry.surface, entry.access, entry.sensitivity) == (
            Surface.MCP,
            Access.READ,
            Sensitivity.BENIGN,
        )

    def test_write_tool_is_mutating(self) -> None:
        (entry,) = manifest_from_mcp_tools(["mcp__claude_ai_Atlassian__createJiraIssue"])
        assert entry.access is Access.WRITE
        assert entry.sensitivity is Sensitivity.MUTATING

    def test_sensitive_read_is_secret(self) -> None:
        (entry,) = manifest_from_mcp_tools(["mcp__claude_ai_Slack__read_dm"])
        assert entry.access is Access.READ
        assert entry.sensitivity is Sensitivity.SECRET


class TestManifestFromCli:
    def test_classifies_and_excludes_internal(self, cli_group: click.Group) -> None:
        entries = manifest_from_cli(cli_group)
        by_name = {e.name: e for e in entries}
        assert by_name["uvx dev10x permission list-rules"].access is Access.READ
        assert by_name["uvx dev10x permission delete-rule"].access is Access.WRITE
        assert by_name["uvx dev10x permission frobnicate"].access is Access.UNKNOWN
        # internal `hook` group excluded
        assert not any(name.startswith("uvx dev10x hook") for name in by_name)

    def test_custom_prog_prefix(self, cli_group: click.Group) -> None:
        entries = manifest_from_cli(cli_group, prog="aws")
        assert all(e.name.startswith("aws ") for e in entries)


class TestManifestFromSkills:
    def test_read_skill(self, tmp_path: Path) -> None:
        _write_skill(
            tmp_path,
            "viewer",
            "---\nname: Dev10x:viewer\nallowed-tools:\n  - Read\n  - Bash(git log:*)\n---\nBody",
        )
        (entry,) = manifest_from_skills(tmp_path)
        assert (entry.surface, entry.name, entry.access) == (Surface.SKILL, "viewer", Access.READ)
        assert entry.sensitivity is Sensitivity.BENIGN

    def test_write_skill_via_edit_tool(self, tmp_path: Path) -> None:
        _write_skill(
            tmp_path,
            "editor",
            "---\nname: Dev10x:editor\nallowed-tools:\n  - Read\n  - Edit\n---\nBody",
        )
        (entry,) = manifest_from_skills(tmp_path)
        assert entry.access is Access.WRITE
        assert entry.sensitivity is Sensitivity.MUTATING

    def test_write_skill_via_bash_write_verb(self, tmp_path: Path) -> None:
        _write_skill(
            tmp_path,
            "creator",
            "---\nname: Dev10x:creator\nallowed-tools:\n  - Bash(gh pr create:*)\n---\nBody",
        )
        (entry,) = manifest_from_skills(tmp_path)
        assert entry.access is Access.WRITE

    def test_malformed_frontmatter_skipped(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "broken", "no frontmatter here\n")
        assert manifest_from_skills(tmp_path) == []

    def test_unterminated_frontmatter_skipped(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "halfbroken", "---\nname: x\nno closing fence\n")
        assert manifest_from_skills(tmp_path) == []

    def test_invalid_yaml_skipped(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "badyaml", "---\n: : :\nbad\n---\nBody")
        assert manifest_from_skills(tmp_path) == []

    def test_non_dict_frontmatter_skipped(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "listfront", "---\n- just\n- a\n- list\n---\nBody")
        assert manifest_from_skills(tmp_path) == []

    def test_missing_allowed_tools_is_read(self, tmp_path: Path) -> None:
        # Valid frontmatter, no external tools → read-only orchestration skill.
        _write_skill(tmp_path, "notools", "---\nname: Dev10x:notools\n---\nBody")
        (entry,) = manifest_from_skills(tmp_path)
        assert entry.access is Access.READ

    def test_non_list_allowed_tools_skipped(self, tmp_path: Path) -> None:
        # Malformed allowed-tools (a string, not a list) → drift signal.
        _write_skill(tmp_path, "strtools", "---\nname: x\nallowed-tools: Read\n---\nBody")
        assert manifest_from_skills(tmp_path) == []

    def test_non_string_tools_ignored(self, tmp_path: Path) -> None:
        _write_skill(
            tmp_path,
            "mixed",
            "---\nname: x\nallowed-tools:\n  - 42\n  - Read\n---\nBody",
        )
        (entry,) = manifest_from_skills(tmp_path)
        assert entry.access is Access.READ


class TestClassifySkillAccess:
    """S15 skill access classifier reusing the unified vocabulary (GH-608)."""

    def test_read_when_all_signals_read(self) -> None:
        assert (
            classify_skill_access(
                name="code-review",
                description="Review the diff and report findings.",
                allowed_tools=["Read", "Bash(git diff:*)"],
            )
            is Access.READ
        )

    def test_write_via_allowed_tools(self) -> None:
        assert (
            classify_skill_access(name="polish", description="Tidy up.", allowed_tools=["Edit"])
            is Access.WRITE
        )

    def test_write_via_name_verb(self) -> None:
        # Write verb in the NAME catches a mutating skill with a sparse
        # frontmatter (no Edit/Write declared, benign description).
        assert (
            classify_skill_access(
                name="ticket-create", description="Helper.", allowed_tools=["Read"]
            )
            is Access.WRITE
        )

    def test_write_via_description_verb(self) -> None:
        assert (
            classify_skill_access(
                name="scaffold",
                description="Create a new module from a template.",
                allowed_tools=[],
            )
            is Access.WRITE
        )

    def test_read_with_defaults(self) -> None:
        # Bare read-only name, no description, no tools → default-safe.
        assert classify_skill_access(name="review") is Access.READ


class TestBuildManifest:
    def test_aggregates_all_surfaces(self, tmp_path: Path, cli_group: click.Group) -> None:
        _write_skill(tmp_path, "viewer", "---\nallowed-tools:\n  - Read\n---\nB")
        manifest = build_manifest(
            mcp_tools=["mcp__claude_ai_Sentry__search_issues"],
            cli_group=cli_group,
            skills_dir=tmp_path,
        )
        surfaces = {e.surface for e in manifest}
        assert surfaces == {Surface.MCP, Surface.CLI, Surface.SKILL}

    def test_sensitivity_override_applied(self, tmp_path: Path, cli_group: click.Group) -> None:
        manifest = build_manifest(
            mcp_tools=["mcp__claude_ai_Google_Drive__read_file_content"],
            cli_group=cli_group,
            skills_dir=tmp_path,
            sensitivity_overrides={
                "mcp__claude_ai_Google_Drive__read_file_content": Sensitivity.PII
            },
        )
        drive = next(e for e in manifest if e.surface is Surface.MCP)
        assert drive.sensitivity is Sensitivity.PII
        assert drive.default_safe is False

    def test_no_overrides_returns_derived(self, tmp_path: Path, cli_group: click.Group) -> None:
        manifest = build_manifest(
            mcp_tools=["mcp__claude_ai_Sentry__search_issues"],
            cli_group=cli_group,
            skills_dir=tmp_path,
        )
        sentry = next(e for e in manifest if e.surface is Surface.MCP)
        assert sentry.sensitivity is Sensitivity.BENIGN


class TestDrift:
    def test_no_drift_when_all_covered(self, tmp_path: Path, cli_group: click.Group) -> None:
        _write_skill(tmp_path, "viewer", "---\nallowed-tools:\n  - Read\n---\nB")
        drift = find_manifest_drift(
            mcp_tools=["mcp__claude_ai_Sentry__search_issues"],
            cli_group=cli_group,
            skills_dir=tmp_path,
        )
        assert drift == []

    def test_drift_when_skill_dropped(self, tmp_path: Path, cli_group: click.Group) -> None:
        # Malformed frontmatter: discovered but not classified → drift.
        _write_skill(tmp_path, "broken", "no frontmatter\n")
        drift = find_manifest_drift(mcp_tools=[], cli_group=cli_group, skills_dir=tmp_path)
        assert drift == ["skill:broken"]

    def test_discovered_keys_cover_all_surfaces(
        self, tmp_path: Path, cli_group: click.Group
    ) -> None:
        _write_skill(tmp_path, "viewer", "---\nallowed-tools:\n  - Read\n---\nB")
        keys = discovered_surface_keys(
            mcp_tools=["mcp__x__get_y"], cli_group=cli_group, skills_dir=tmp_path
        )
        assert ("mcp", "mcp__x__get_y") in keys
        assert ("skill", "viewer") in keys
        assert ("cli", "uvx dev10x permission list-rules") in keys
        assert not any(surface == "cli" and "hook" in name for surface, name in keys)


class TestLiveManifestHasNoDrift:
    """CI gate: every live plugin surface must classify into the manifest."""

    def test_no_drift_across_all_surfaces(self) -> None:
        mcp_tools = [tool for tools in discover_mcp_tools().values() for tool in tools]
        drift = find_manifest_drift(
            mcp_tools=mcp_tools,
            cli_group=cli,
            skills_dir=PLUGIN_SKILLS,
        )
        assert drift == [], f"Surfaces missing from the manifest: {drift}"

    def test_catalog_path_exists(self) -> None:
        # The manifest lives beside the curated catalog it validates.
        assert (Path(permission_pkg.__file__).parent / "baseline-permissions.yaml").is_file()
