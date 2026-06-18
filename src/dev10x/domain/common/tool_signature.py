"""ToolSignature value object — canonical ``Tool(value)`` string identity.

Tool-call signatures appeared in three modules as parallel string-building
and rule-suggestion logic (GH-543):

- ``hooks/permission_diagnostics.py`` — ``extract_tool_signature`` +
  ``_suggest_rule``
- ``audit/permissions_model.py`` — ``ToolCall.signature()``
- ``skills/audit/analyze_actions.py`` — ``classify_action`` +
  ``ACTION_TYPE_BY_TOOL``

This object is the single authoritative place for all three concerns.
Each module's public functions and methods are preserved unchanged; they
now delegate here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dev10x.domain.common.mcp_tool_name import McpToolName

_PATH_TOOLS = frozenset({"Write", "Read", "Edit"})

# Action-type mapping used by the skill-audit action inventory.
# Keys are exact tool names; value is the canonical action-type string
# emitted in Phase 1 output tables.
ACTION_TYPE_BY_TOOL: dict[str, str] = {
    "Skill": "Skill",
    "Agent": "Agent",
    "TaskCreate": "Task",
    "TaskUpdate": "Task",
    "TaskList": "Task",
    "TaskGet": "Task",
    "AskUserQuestion": "Decision",
    "Write": "CodeChange",
    "Edit": "CodeChange",
    "Read": "Read",
    "Glob": "Search",
    "Grep": "Search",
    "WebFetch": "Web",
    "WebSearch": "Web",
}


@dataclass(frozen=True)
class ToolSignature:
    """Canonical ``Tool(value)`` string for a single Claude tool call.

    Constructed from a tool name and an optional value (command text or
    file path).  The :meth:`build` factory covers the three shapes that
    appear in permission diagnostics:

    - ``Bash(<command>)``
    - ``Write/Read/Edit(<file_path>)``
    - ``<mcp_tool_name>`` (returned as-is — MCP tools carry no argument)
    - ``<tool_name>()`` (fallback for any other tool)

    For MCP tools the value is ignored and the tool name is returned as
    the signature verbatim (MCP identifiers are self-contained).
    """

    tool: str
    value: str

    def __str__(self) -> str:
        if McpToolName.is_mcp(self.tool):
            return self.tool
        return f"{self.tool}({self.value})"

    # ------------------------------------------------------------------
    # Factory helpers
    # ------------------------------------------------------------------

    @classmethod
    def build(
        cls,
        *,
        tool_name: str,
        command: str = "",
        file_path: str = "",
    ) -> ToolSignature:
        """Build a :class:`ToolSignature` from raw tool-call components.

        ``tool_name`` is required.  Provide ``command`` for Bash calls and
        ``file_path`` for Write/Read/Edit calls.  For MCP tools neither is
        needed.
        """
        if tool_name == "Bash":
            return cls(tool=tool_name, value=command)
        if tool_name in _PATH_TOOLS:
            return cls(tool=tool_name, value=file_path)
        return cls(tool=tool_name, value="")

    @classmethod
    def from_hook_input(cls, raw: dict[str, Any]) -> ToolSignature | None:
        """Parse a ``ToolSignature`` from a raw hook-input dict.

        Returns ``None`` when ``tool_name`` is absent or empty, or when a
        Bash/path tool has no usable value (matching the previous
        ``extract_tool_signature`` contract).
        """
        tool_name: str = raw.get("tool_name", "")
        tool_input: dict[str, Any] = raw.get("tool_input", {})

        if not tool_name:
            return None

        if tool_name == "Bash":
            command: str = tool_input.get("command", "")
            if not command:
                return None
            return cls(tool=tool_name, value=command)

        if tool_name in _PATH_TOOLS:
            file_path: str = tool_input.get("file_path", "")
            if not file_path:
                return None
            return cls(tool=tool_name, value=file_path)

        return cls(tool=tool_name, value="")

    # ------------------------------------------------------------------
    # Rule suggestion
    # ------------------------------------------------------------------

    def suggest_rule(self) -> str:
        """Return the narrowest allow-rule that would cover this signature.

        - MCP tools → ``mcp__<server>__*`` (server wildcard)
        - ``Bash(<command>)`` → ``Bash(<first-word>:*)``
        - ``Write/Read/Edit(<path>)`` → ``Write/Read/Edit(<parent>/**)``
        - other ``Tool(value)`` → signature unchanged
        """
        sig = str(self)

        if McpToolName.is_mcp(sig):
            last_sep = sig.rfind("__")
            if last_sep > 0:
                prefix = sig[:last_sep]
                return f"{prefix}__*"
            return sig

        paren_idx = sig.find("(")
        if paren_idx == -1:
            return sig

        tool = sig[:paren_idx]
        value = sig[paren_idx + 1 :].rstrip(")")

        if tool == "Bash":
            first_space = value.find(" ")
            if first_space > 0:
                return f"Bash({value[:first_space]}:*)"
            return f"Bash({value}:*)"

        if tool in _PATH_TOOLS:
            parent = str(Path(value).parent)
            return f"{tool}({parent}/**)"

        return sig

    # ------------------------------------------------------------------
    # Action classification (Phase 1 audit)
    # ------------------------------------------------------------------

    def classify_action(self, input_summary: str = "") -> str:
        """Return the action-type string for the Phase 1 action inventory.

        Delegates to :data:`ACTION_TYPE_BY_TOOL` for known tools, applies
        keyword-based Bash classification, and falls back to ``"Other"``.
        """
        mapped = ACTION_TYPE_BY_TOOL.get(self.tool)
        if mapped is not None:
            return mapped
        if self.tool == "Bash":
            return _classify_bash(input_summary=input_summary)
        return "Other"


# Action keywords used by _classify_bash — kept at module scope so
# callers that need the raw dict (e.g. tests) can import it.
ACTION_KEYWORDS: dict[str, list[str]] = {
    "Git": [
        "git commit",
        "git push",
        "git rebase",
        "git checkout",
        "git merge",
        "git branch",
        "git fetch",
        "git pull",
        "git stash",
        "git cherry-pick",
        "git reset",
        "git log",
        "git diff",
        "git add",
        "git tag",
    ],
    "PR": [
        "gh pr ",
        "pr create",
        "pr view",
        "pr merge",
        "pr ready",
        "pr checks",
        "pr review",
        "pr comment",
        "pr diff",
    ],
    "Issue": ["gh issue", "issue view", "issue create", "issue comment"],
    "Test": ["pytest", "uv run pytest", "python -m pytest", "coverage"],
    "Lint": ["ruff", "black", "isort", "mypy", "flake8"],
    "CodeChange": [],
    "Config": ["settings.json", "settings.local.json", "chmod", "uv.lock"],
}


def _classify_bash(input_summary: str) -> str:
    combined = f"Bash {input_summary}".lower()
    for action_type, keywords in ACTION_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in combined:
                return action_type
    return "Other"
