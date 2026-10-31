from __future__ import annotations

from html import escape

from dev10x.comm.supervisor.decisions import Decision
from dev10x.comm.supervisor.delivery import keys_for_permission
from dev10x.comm.supervisor.probes import Snapshot
from dev10x.comm.supervisor.sessions import GROUPS, SessionView

REFRESH_SECONDS = 5
PERMISSION_PROMPT = "permission prompt"
REFRESH_SCRIPT = (
    "setInterval(function () {"
    " var typing = Array.prototype.some.call("
    "document.querySelectorAll('input[type=text]'), function (i) { return i.value; });"
    " if (!typing) { location.reload(); } }, %d);"
)
TITLES = {"needs-you": "Needs you", "working": "Working", "done": "Done"}

STYLE = """
:root { --bg: #fafafa; --fg: #1d1d1f; --muted: #6e6e73; --card: #fff; --line: #d2d2d7;
  --accent: #0a66c2; --warn: #b25000; }
@media (prefers-color-scheme: dark) { :root { --bg: #141416; --fg: #f2f2f7;
  --muted: #a1a1a6; --card: #1f1f22; --line: #3a3a3c; --accent: #4ea1ff; --warn: #ffb35c; } }
body { margin: 0; padding: 16px; background: var(--bg); color: var(--fg);
  font: 15px/1.45 system-ui, sans-serif; }
main { max-width: 960px; margin: 0 auto; }
h2 { font-size: 17px; margin: 24px 0 8px; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 8px;
  padding: 10px 12px; margin: 8px 0; overflow-wrap: anywhere; }
.meta { color: var(--muted); font-size: 13px; }
.waiting { color: var(--warn); font-weight: 600; }
pre { white-space: pre-wrap; font-size: 12px; max-height: 18em; overflow: auto; }
form { display: inline; margin: 0 6px 6px 0; }
button { font: inherit; padding: 4px 10px; border-radius: 6px; border: 1px solid var(--accent);
  background: transparent; color: var(--accent); cursor: pointer; }
input[type=text] { font: inherit; width: min(32em, 100%); }
.error { color: var(--warn); }
"""


def _hidden(*, name: str, value: str) -> str:
    return f'<input type="hidden" name="{escape(name)}" value="{escape(value)}">'


def _button_form(*, action: str, token: str, fields: dict[str, str], label: str) -> str:
    hidden = "".join(_hidden(name=key, value=value) for key, value in fields.items())
    return (
        f'<form method="post" action="{action}">{_hidden(name="token", value=token)}'
        f"{hidden}<button>{escape(label)}</button></form>"
    )


def _decision_html(*, decision: Decision, token: str) -> str:
    buttons = "".join(
        _button_form(
            action="/answer",
            token=token,
            fields={"decision_id": decision.decision_id, "option_index": str(index)},
            label=option,
        )
        for index, option in enumerate(decision.options)
    )
    return (
        f'<div class="decision"><strong>{escape(decision.header)}</strong> '
        f"{escape(decision.question)}<div>{buttons}</div></div>"
    )


def _permission_html(*, view: SessionView, pane_text: str, token: str) -> str:
    allow, deny = keys_for_permission(allow=True), keys_for_permission(allow=False)
    return (
        f"<pre>{escape(pane_text)}</pre>"
        + _button_form(
            action="/keys",
            token=token,
            fields={"session_id": view.session_id, "allow": "1"},
            label=f"Send {' '.join(allow)} (allow)",
        )
        + _button_form(
            action="/keys",
            token=token,
            fields={"session_id": view.session_id, "allow": "0"},
            label=f"Send {' '.join(deny)} (deny)",
        )
    )


def _reply_html(*, view: SessionView, token: str) -> str:
    return (
        f'<form method="post" action="/reply">{_hidden(name="token", value=token)}'
        f"{_hidden(name='session_id', value=view.session_id)}"
        '<input type="text" name="text" aria-label="Reply" placeholder="Reply via relay">'
        " <button>Send</button></form>"
    )


def _session_html(
    *,
    view: SessionView,
    decisions: list[Decision],
    pane_text: str,
    token: str,
) -> str:
    label = f"{view.callsign} [{view.name}]" if view.callsign else view.name
    waiting = (
        f' <span class="waiting">{escape(view.waiting_for)}</span>' if view.waiting_for else ""
    )
    parts = [
        f"<strong>{escape(label)}</strong>{waiting}",
        f'<div class="meta">{escape(view.cwd)} · {escape(view.status)}'
        f"{' · ' + escape(view.pane_id) if view.pane_id else ''}</div>",
    ]
    if view.summary:
        parts.append(f"<div>{escape(view.summary)}</div>")
    parts.extend(_decision_html(decision=decision, token=token) for decision in decisions)
    if view.group == "needs-you":
        if view.waiting_for == PERMISSION_PROMPT and view.pane_id:
            parts.append(_permission_html(view=view, pane_text=pane_text, token=token))
        elif not decisions:
            if pane_text:
                parts.append(f"<pre>{escape(pane_text)}</pre>")
            parts.append(_reply_html(view=view, token=token))
    return f'<div class="card">{"".join(parts)}</div>'


def render_page(
    *,
    snapshot: Snapshot,
    decisions: list[Decision],
    pane_text: dict[str, str],
    token: str,
) -> str:
    by_session: dict[str, list[Decision]] = {}
    for decision in decisions:
        by_session.setdefault(decision.session_id, []).append(decision)
    sections = []
    for group in GROUPS:
        views = [view for view in snapshot.sessions if view.group == group]
        cards = "".join(
            _session_html(
                view=view,
                decisions=by_session.get(view.session_id, []),
                pane_text=pane_text.get(view.session_id, ""),
                token=token,
            )
            for view in views
        )
        sections.append(f"<section><h2>{TITLES[group]} ({len(views)})</h2>{cards}</section>")
    errors = "".join(
        f'<p class="error">{escape(source)}: {escape(message)}</p>'
        for source, message in sorted(snapshot.errors.items())
    )
    stamp = snapshot.taken_at.strftime("%H:%M:%S")
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>Session Supervisor</title><style>{STYLE}</style></head>"
        f'<body><main><h1>Session Supervisor</h1><p class="meta">Updated {stamp}</p>'
        f"{errors}{''.join(sections)}</main>"
        f"<script>{REFRESH_SCRIPT % (REFRESH_SECONDS * 1000)}</script></body></html>"
    )
