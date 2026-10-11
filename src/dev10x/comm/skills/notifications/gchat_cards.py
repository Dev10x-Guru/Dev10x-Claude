"""Google Chat cardsV2 construction helpers (GH-1113).

Pure formatting — no I/O and no network; ``gchat_notify`` owns the
transport. A plain-text Chat message accepts ``*bold*`` markup, but a
card's ``textParagraph`` renders an HTML subset instead, so markup a
caller already writes has to be translated before it reaches a panel.

Supported ``textParagraph`` tags per the Chat API reference: ``<b>``,
``<i>``, ``<u>``, ``<s>``, ``<font color>``, ``<a href>``, ``<time>``,
``<br>``, ``<code>``, ``<pre>``, ``<ul>``, ``<ol>``, ``<li>``.

Card text does NOT render user mentions — ``<users/ID>`` tokens only
notify from a message's ``text`` field. Send mentions as ``text``
alongside the card rather than inside it.
"""

from __future__ import annotations

import html
import re
from typing import Any

_SENTINEL = "\x00"

_MD_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
_CHAT_LINK = re.compile(r"<(https?://[^\s|>]+)\|([^>]+)>")
_BARE_LINK = re.compile(r"<(https?://[^\s|>]+)>")
_CODE_SPAN = re.compile(r"`([^`]+)`")

_BULLET_ITEM = re.compile(r"^[-*+]\s+(.*)$")
_NUMBERED_ITEM = re.compile(r"^\d+[.)]\s+(.*)$")
_QUOTE_LINE = re.compile(r"^&gt;\s?(.*)$")

_EMPHASIS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\*\*(.+?)\*\*"), r"<b>\1</b>"),
    (re.compile(r"(?<!\w)\*(.+?)\*(?!\w)"), r"<b>\1</b>"),
    (re.compile(r"(?<!\w)_(.+?)_(?!\w)"), r"<i>\1</i>"),
    (re.compile(r"(?<!\w)~(.+?)~(?!\w)"), r"<s>\1</s>"),
)


def _protect(text: str) -> tuple[str, list[str]]:
    """Swap links and code spans for sentinels holding rendered HTML.

    Extraction happens before escaping so a URL's own ``&`` is escaped
    exactly once, and inline-emphasis passes cannot reach inside a code
    span or a link's href.
    """
    tokens: list[str] = []

    def _store(rendered: str) -> str:
        tokens.append(rendered)
        return f"{_SENTINEL}{len(tokens) - 1}{_SENTINEL}"

    def _link(*, url: str, label: str) -> str:
        href = html.escape(url, quote=True)
        return _store(f'<a href="{href}">{html.escape(label, quote=False)}</a>')

    text = text.replace(_SENTINEL, "")
    text = _CODE_SPAN.sub(lambda m: _store(f"<code>{html.escape(m.group(1))}</code>"), text)
    text = _MD_LINK.sub(lambda m: _link(url=m.group(2), label=m.group(1)), text)
    text = _CHAT_LINK.sub(lambda m: _link(url=m.group(1), label=m.group(2)), text)
    text = _BARE_LINK.sub(lambda m: _link(url=m.group(1), label=m.group(1)), text)
    return text, tokens


def _restore(text: str, tokens: list[str]) -> str:
    for index, rendered in enumerate(tokens):
        text = text.replace(f"{_SENTINEL}{index}{_SENTINEL}", rendered)
    return text


def _apply_emphasis(line: str) -> str:
    for pattern, replacement in _EMPHASIS:
        line = pattern.sub(replacement, line)
    return line


def _render_list(*, items: list[str], ordered: bool) -> str:
    tag = "ol" if ordered else "ul"
    rendered = "".join(f"<li>{_apply_emphasis(item)}</li>" for item in items)
    return f"<{tag}>{rendered}</{tag}>"


def md_to_card_html(text: str) -> str:
    """Translate Chat/markdown message markup into card-paragraph HTML."""
    protected, tokens = _protect(text)
    parts: list[str] = []
    pending_items: list[str] = []
    pending_ordered = False

    def _flush() -> None:
        nonlocal pending_items
        if pending_items:
            parts.append(_render_list(items=pending_items, ordered=pending_ordered))
            pending_items = []

    for raw_line in html.escape(protected, quote=False).split("\n"):
        line = raw_line.strip()
        numbered = _NUMBERED_ITEM.match(line)
        item = numbered or _BULLET_ITEM.match(line)
        if item is not None:
            ordered = numbered is not None
            if pending_items and ordered != pending_ordered:
                _flush()
            pending_ordered = ordered
            pending_items.append(item.group(1))
            continue
        _flush()
        quoted = _QUOTE_LINE.match(line)
        if quoted:
            parts.append(f"<i>{_apply_emphasis(quoted.group(1))}</i>")
            continue
        parts.append(_apply_emphasis(line))
    _flush()

    return _restore("<br>".join(parts), tokens)


def plain_text_fallback(text: str) -> str:
    """Reduce markup to a single readable line for ``fallbackText``.

    Chat shows this in mobile notifications when the card cannot render,
    so it must stay plain — markers dropped, links reduced to their label.
    """
    text = _CODE_SPAN.sub(r"\1", text)
    text = _MD_LINK.sub(r"\1", text)
    text = _CHAT_LINK.sub(r"\2", text)
    text = _BARE_LINK.sub(r"\1", text)
    text = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*>\s?", "", text, flags=re.MULTILINE)
    for pattern, _ in _EMPHASIS:
        text = pattern.sub(r"\1", text)
    return " ".join(text.split())


def text_paragraph(text: str, *, max_lines: int | None = None) -> dict[str, Any]:
    """Build a ``textParagraph`` widget, translating markup to card HTML."""
    widget: dict[str, Any] = {"text": md_to_card_html(text)}
    if max_lines is not None:
        widget["maxLines"] = max_lines
    return {"textParagraph": widget}


def divider() -> dict[str, Any]:
    return {"divider": {}}


def link_button(*, text: str, url: str) -> dict[str, Any]:
    return {"text": text, "onClick": {"openLink": {"url": url}}}


def button_list(buttons: list[dict[str, Any]]) -> dict[str, Any]:
    return {"buttonList": {"buttons": buttons}}


def section(
    *,
    widgets: list[dict[str, Any]],
    header: str | None = None,
    collapsible: bool = False,
    uncollapsible_widgets_count: int | None = None,
) -> dict[str, Any]:
    built: dict[str, Any] = {"widgets": widgets}
    if header is not None:
        built["header"] = header
    if collapsible:
        built["collapsible"] = True
        if uncollapsible_widgets_count is not None:
            built["uncollapsibleWidgetsCount"] = uncollapsible_widgets_count
    return built


def card(
    *,
    card_id: str,
    sections: list[dict[str, Any]],
    title: str | None = None,
    subtitle: str | None = None,
    image_url: str | None = None,
    image_type: str = "CIRCLE",
) -> dict[str, Any]:
    """Build one ``CardWithId`` entry for a message's ``cardsV2`` array."""
    body: dict[str, Any] = {"sections": sections}
    if title is not None:
        header: dict[str, Any] = {"title": title}
        if subtitle is not None:
            header["subtitle"] = subtitle
        if image_url is not None:
            header["imageUrl"] = image_url
            header["imageType"] = image_type
        body["header"] = header
    return {"cardId": card_id, "card": body}


def simple_card(
    *,
    card_id: str,
    body: str,
    title: str | None = None,
    subtitle: str | None = None,
    buttons: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Wrap one markup body (plus optional buttons) in a single-section card."""
    widgets: list[dict[str, Any]] = [text_paragraph(body)]
    if buttons:
        widgets.append(button_list(buttons))
    return card(
        card_id=card_id,
        sections=[section(widgets=widgets)],
        title=title,
        subtitle=subtitle,
    )
