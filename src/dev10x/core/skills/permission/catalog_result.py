"""The result-dict shape every permission catalog operation returns (GH-1432).

``ensure_base``, ``ensure_scripts``, ``generalize``, ``init`` and their
siblings all hand back the same ``{exit_code, messages, errors,
total_added, files_changed}`` mapping, which the CLI and MCP layers print
and act on. It lives in its own module so the load and write halves of the
catalog can both build it without importing each other.
"""

from __future__ import annotations


def _result(
    *,
    exit_code: int,
    messages: list[str],
    errors: list[str],
    total_added: int = 0,
    files_changed: int = 0,
) -> dict[str, object]:
    return {
        "exit_code": exit_code,
        "messages": messages,
        "errors": errors,
        "total_added": total_added,
        "files_changed": files_changed,
    }
