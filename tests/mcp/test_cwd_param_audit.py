"""Guard the GH-1122 strict-argument seam against a `cwd=` regression.

Making unknown kwargs fail loud flips a habit into a hazard: skills pass
`cwd=` freely (GH-979), and a tool that does not declare it went from
silently ignoring the key to erroring. This pins the set of tools without
a `cwd` parameter so adding one to that set is a deliberate act with a
visible diff, not a surprise at call time.
"""

from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def tool_names_without_cwd() -> set[str]:
    from dev10x.mcp.server_cli import server

    return {
        tool.name
        for tool in server._tool_manager.list_tools()
        if "cwd" not in set(tool.fn_metadata.arg_model.model_fields)
    }


def test_cwd_less_tools_are_only_the_context_free_ones(
    tool_names_without_cwd: set[str],
) -> None:
    # Guard against a vacuous pass: some tools legitimately take no cwd
    # (temp-file creation, session/usage lookups, sampling), so an empty
    # set would mean the introspection broke rather than that all is well.
    assert tool_names_without_cwd

    # A GitHub or git tool appearing in this set is the regression to
    # catch — those are exactly the ones callers pass `cwd=` to.
    for name in tool_names_without_cwd:
        assert not name.startswith(("pr_", "issue_", "milestone_")), (
            f"{name} takes no `cwd` but is a repo-scoped tool; callers pass "
            "cwd= to these and GH-1122 now rejects unknown kwargs"
        )
