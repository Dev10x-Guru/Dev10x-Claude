"""dev10x.github splits by capability behind one seam (ADR-0027, GH-1478).

Two guards, both landed before any capability moved (ADR-0027 D4):

* the split shape — the facade still answers every pre-split name, and
  capability modules never import the facade back;
* the patch-target guard — a test that patches ``dev10x.github.<name>``
  when the package's own code looks ``<name>`` up somewhere else is
  patching a copy nobody calls. It still "succeeds", so without this
  guard the test goes quietly false-green.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

gh = pytest.importorskip("dev10x.github", reason="dev10x not installed")

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / "src" / "dev10x" / "github"
TESTS_DIR = REPO_ROOT / "tests"

CAPABILITY_MODULES = (
    "_gateway",
    "detection",
    "reviews",
    "labels",
    "pulls",
    "merge",
    "milestones",
    "issues",
    "bulk",
    "notify",
)

GATEWAY_REIMPORTS = frozenset({"AppConfig", "async_run", "async_run_script", "get_bot_token"})

PRE_SPLIT_NAMES = (
    "_GH_RETRY_POLICY",
    "_BASE_BRANCH_NAMES",
    "_detect_repo",
    "_gh_api_raw",
    "_gh_api",
    "_bot_env",
    "_resolve_repo",
    "_parse_gh_api_result",
    "_run_and_parse",
    "detect_tracker",
    "pr_detect",
    "pr_get",
    "issue_get",
    "issue_comments",
    "issue_create",
    "_pr_comment_get",
    "_pr_comment_list",
    "_BOT_LOGIN_RE",
    "is_bot_login",
    "_list_unresolved_threads",
    "_REACTION_GROUP_CONTENT_TO_KEY",
    "_normalize_reaction_groups",
    "_pr_comment_reply",
    "_pr_comment_edit",
    "_pr_comment_resolve",
    "_PR_COMMENT_ACTIONS",
    "_MINIMIZE_CLASSIFIERS",
    "minimize_comments",
    "resolve_review_thread",
    "pr_comments",
    "pr_comment_reply",
    "pr_comment_edit",
    "PR_LABEL_ACTIONS",
    "_loads_or_empty",
    "_label_names",
    "_current_label_names",
    "pr_labels",
    "issue_labels",
    "pr_review_edit",
    "pr_issue_comment",
    "request_review",
    "detect_base_branch",
    "verify_pr_state",
    "pre_pr_checks",
    "_resolve_milestone_number",
    "_set_pr_milestone",
    "create_pr",
    "update_pr",
    "_normalized_for_comparison",
    "_unapplied_pr_fields",
    "_resolve_merge_bot",
    "_merge_as_bot",
    "merge_pr",
    "pr_ready",
    "pr_close",
    "pr_list",
    "milestone_close",
    "milestone_create",
    "milestone_reopen",
    "milestone_edit",
    "milestone_list",
    "_issue_result",
    "issue_edit",
    "_CLOSE_REASON_GH_VALUE",
    "issue_close",
    "issue_reopen",
    "_resolve_comment_body",
    "issue_comment",
    "issue_comment_edit",
    "issue_comment_delete",
    "issue_list",
    "triage_roster",
    "_bulk_execute",
    "milestones_bulk_create",
    "issues_bulk_create",
    "issues_bulk_edit",
    "generate_commit_list",
    "post_summary_comment",
    "pr_notify",
    "check_top_level_comments",
    "unresolved_threads",
)

# Names still defined in __init__.py while the phased split runs. Each
# capability move deletes its names here; the split is done when the
# facade defines nothing.
AWAITING_MOVE = frozenset(
    set(PRE_SPLIT_NAMES)
    - {
        "_GH_RETRY_POLICY",
        "_detect_repo",
        "_gh_api_raw",
        "_gh_api",
        "_bot_env",
        "_resolve_repo",
        "_parse_gh_api_result",
        "_run_and_parse",
        "generate_commit_list",
        "post_summary_comment",
        "pr_notify",
        "_resolve_milestone_number",
        "milestone_close",
        "milestone_create",
        "milestone_reopen",
        "milestone_edit",
        "milestone_list",
        "detect_tracker",
        "pr_detect",
        "detect_base_branch",
        "verify_pr_state",
        "pre_pr_checks",
    }
)

# A facade patch is right when the code under test resolves the name
# FROM the facade, not from a capability module. These external
# consumers do exactly that at call time.
EXTERNAL_FACADE_LOOKUPS = frozenset(
    {
        # skills/notifications/_gh.py: `from dev10x.github import _gh_api_raw`
        ("tests/skills/notifications/test_gh.py", "_gh_api_raw"),
    }
)


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _existing_capability_modules() -> list[str]:
    return [name for name in CAPABILITY_MODULES if (PACKAGE_DIR / f"{name}.py").exists()]


def _top_level_definitions(tree: ast.Module) -> set[str]:
    defined: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            defined.add(node.name)
        elif isinstance(node, ast.Assign):
            defined.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defined.add(node.target.id)
    defined.discard("__all__")
    return defined


def internal_lookups() -> dict[str, list[str]]:
    """Map each name to the modules whose code resolves it off the facade.

    A bare load inside ``__init__`` resolves through the facade's own
    globals, so a facade patch reaches it. A bare load in a capability
    module, or any ``<module>.<name>`` attribute access, resolves
    somewhere a facade patch never touches.
    """
    lookups: dict[str, list[str]] = {}
    for module in ["__init__", *_existing_capability_modules()]:
        for node in ast.walk(_parse(PACKAGE_DIR / f"{module}.py")):
            if isinstance(node, ast.Attribute):
                lookups.setdefault(node.attr, []).append(module)
            elif (
                module != "__init__"
                and isinstance(node, ast.Name)
                and isinstance(node.ctx, ast.Load)
            ):
                lookups.setdefault(node.id, []).append(module)
    return lookups


def _facade_aliases(tree: ast.Module) -> set[str]:
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            aliases.update(
                alias.asname
                for alias in node.names
                if alias.name == "dev10x.github" and alias.asname
            )
        elif isinstance(node, ast.ImportFrom) and node.module == "dev10x":
            aliases.update(
                alias.asname or alias.name for alias in node.names if alias.name == "github"
            )
        elif (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == "importorskip"
            and node.value.args
            and isinstance(node.value.args[0], ast.Constant)
            and node.value.args[0].value == "dev10x.github"
        ):
            aliases.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return aliases


def _is_patch(func: ast.expr) -> bool:
    return (isinstance(func, ast.Name) and func.id == "patch") or (
        isinstance(func, ast.Attribute) and func.attr == "patch"
    )


def _is_object_patch(func: ast.expr) -> bool:
    return isinstance(func, ast.Attribute) and (
        func.attr == "setattr" or (func.attr == "object" and _is_patch(func.value))
    )


def facade_patch_targets(tree: ast.Module) -> list[tuple[int, str]]:
    """Every ``(line, name)`` a test patches directly on the facade."""
    aliases = _facade_aliases(tree)
    targets: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        first = node.args[0]
        if _is_patch(node.func) and isinstance(first, ast.Constant):
            dotted = str(first.value)
            if dotted.startswith("dev10x.github.") and "." not in dotted[len("dev10x.github.") :]:
                targets.append((node.lineno, dotted[len("dev10x.github.") :]))
        elif (
            _is_object_patch(node.func)
            and isinstance(first, ast.Name)
            and first.id in aliases
            and len(node.args) > 1
            and isinstance(node.args[1], ast.Constant)
        ):
            targets.append((node.lineno, str(node.args[1].value)))
    return targets


def facade_patch_violations(
    *,
    tree: ast.Module,
    relative_path: str,
    lookups: dict[str, list[str]],
) -> list[str]:
    violations: list[str] = []
    for line, name in facade_patch_targets(tree):
        if (PACKAGE_DIR / f"{name}.py").exists() or (
            relative_path,
            name,
        ) in EXTERNAL_FACADE_LOOKUPS:
            continue
        elsewhere = sorted(set(lookups.get(name, [])))
        if elsewhere:
            violations.append(
                f"{relative_path}:{line} patches dev10x.github.{name}, but "
                f"{', '.join(elsewhere)} resolve it elsewhere — patch the defining "
                f"module instead"
            )
    return violations


@pytest.fixture(scope="module")
def lookups() -> dict[str, list[str]]:
    return internal_lookups()


@pytest.fixture(scope="module")
def init_tree() -> ast.Module:
    return _parse(PACKAGE_DIR / "__init__.py")


class TestFacadeShape:
    @pytest.mark.parametrize("name", PRE_SPLIT_NAMES)
    def test_facade_still_answers_pre_split_name(self, name: str) -> None:
        assert hasattr(gh, name)

    def test_all_lists_exactly_the_pre_split_names(self) -> None:
        assert sorted(gh.__all__) == sorted(PRE_SPLIT_NAMES)

    def test_facade_defines_only_names_awaiting_their_move(self, init_tree: ast.Module) -> None:
        assert _top_level_definitions(init_tree) == AWAITING_MOVE

    @pytest.mark.parametrize("module", _existing_capability_modules())
    def test_capability_module_does_not_import_the_facade(self, module: str) -> None:
        tree = _parse(PACKAGE_DIR / f"{module}.py")

        facade_imports = [
            node.lineno
            for node in ast.walk(tree)
            if (
                isinstance(node, ast.Import) and any(a.name == "dev10x.github" for a in node.names)
            )
            or (
                isinstance(node, ast.ImportFrom)
                and node.module in {"dev10x", "dev10x.github"}
                and any(not (PACKAGE_DIR / f"{a.name}.py").exists() for a in node.names)
            )
        ]

        assert facade_imports == []

    @pytest.mark.parametrize(
        "module", [m for m in _existing_capability_modules() if m != "_gateway"]
    )
    def test_capability_module_reaches_dependencies_through_the_seam(self, module: str) -> None:
        tree = _parse(PACKAGE_DIR / f"{module}.py")

        bound_by_name = [
            f"{node.module}:{alias.name}"
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
            if alias.name in GATEWAY_REIMPORTS or (node.module or "").startswith("dev10x.github.")
        ]

        assert bound_by_name == []


class TestPatchTargetGuard:
    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ('patch("dev10x.github._gh_api_raw")', [(1, "_gh_api_raw")]),
            ('patch("dev10x.github._gateway._gh_api_raw")', []),
            ('import dev10x.github as g\npatch.object(g, "_detect_repo")', [(2, "_detect_repo")]),
            ('import dev10x.github as g\npatch.object(g._gateway, "_detect_repo")', []),
            (
                'from dev10x import github\nmonkeypatch.setattr(github, "async_run", f)',
                [(2, "async_run")],
            ),
        ],
    )
    def test_finds_facade_patch_targets(
        self, source: str, expected: list[tuple[int, str]]
    ) -> None:
        assert facade_patch_targets(ast.parse(source)) == expected

    def test_flags_a_facade_patch_of_a_seam_dependency(
        self, lookups: dict[str, list[str]]
    ) -> None:
        violations = facade_patch_violations(
            tree=ast.parse('patch("dev10x.github._gh_api_raw")'),
            relative_path="tests/example.py",
            lookups=lookups,
        )

        assert len(violations) == 1

    def test_no_test_patches_a_copy_nobody_calls(self, lookups: dict[str, list[str]]) -> None:
        violations = [
            violation
            for path in sorted(TESTS_DIR.rglob("*.py"))
            for violation in facade_patch_violations(
                tree=_parse(path),
                relative_path=str(path.relative_to(REPO_ROOT)),
                lookups=lookups,
            )
        ]

        assert violations == []
