"""MCP prompt registrations for Dev10x workflow templates (GH-340).

Exposes reusable, parametrized prompt templates as MCP prompts so
clients can invoke them with argument autocomplete instead of
re-deriving Dev10x conventions by hand. Each prompt mirrors the
intent of its namesake skill (Dev10x:review, Dev10x:git-commit,
Dev10x:jtbd) without re-implementing the skill's orchestration — the
returned text is a ready-to-run instruction the client model acts on.

Prompts:
    review(target, focus)    — structured self-review instruction
    commit(summary, ticket)  — Dev10x-formatted commit message
    jtbd(context)            — JTBD Job Story draft

Function parameters become the prompt's arguments (required when they
have no default, optional otherwise), which clients surface as
argument autocomplete. Registered on import via the FastMCP
``@server.prompt()`` decorator; ``server_cli.py`` imports this module
to trigger registration.
"""

from __future__ import annotations

from dev10x.mcp._app import server


@server.prompt(
    name="review",
    title="Dev10x self-review",
    description="Review a branch or diff against Dev10x review guidelines",
)
def review(target: str = "the current branch", focus: str = "") -> str:
    """Return a structured review instruction for *target*."""
    focus_line = f"\nFocus especially on: {focus}." if focus.strip() else ""
    return (
        f"Review {target} against the project's code-review guidelines."
        f"{focus_line}\n\n"
        "Cover correctness, tests, architecture, and security. For each "
        "finding, report severity (ERROR/WARNING/INFO), file:line, a short "
        "description, and a suggested fix. Skip pure style preferences no "
        "documented rule covers. End with a one-line verdict: ship, "
        "fix-then-ship, or needs-discussion."
    )


@server.prompt(
    name="commit",
    title="Dev10x commit message",
    description="Draft a gitmoji + ticket + JTBD-outcome commit message",
)
def commit(summary: str, ticket: str = "") -> str:
    """Return commit-message drafting guidance for *summary*."""
    ticket_line = (
        f"Use ticket id `{ticket}` in the title and a `Fixes: {ticket}` footer."
        if ticket.strip()
        else "Extract the ticket id from the branch name; if none, omit the "
        "ticket reference and the Fixes footer."
    )
    return (
        f"Draft a commit message for this change: {summary}\n\n"
        "Format:\n"
        "- Title: `<gitmoji> <TICKET-ID> <outcome>` — describe what the change "
        "ENABLES (e.g. 'Enable X'), not what was added. Max 72 characters.\n"
        f"- {ticket_line}\n"
        "- Body: one short paragraph on the problem, then a `Solution:` list "
        "of bullet points.\n"
        "- No Co-Authored-By footer."
    )


@server.prompt(
    name="jtbd",
    title="Dev10x Job Story",
    description="Draft a JTBD Job Story for a ticket, PR, or feature",
)
def jtbd(context: str) -> str:
    """Return a JTBD Job Story drafting instruction for *context*."""
    return (
        f"Draft a JTBD Job Story for: {context}\n\n"
        "Use first-person, situation-driven voice in exactly this shape:\n"
        "**When** <situation>, **I want to** <motivation>, **so I can** "
        "<expected outcome>.\n\n"
        "Name the actor and beneficiary explicitly. Describe the outcome, not "
        "the implementation. Keep it to one or two sentences."
    )
