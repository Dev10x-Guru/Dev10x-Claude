"""Tests for the gchat_cards formatting module (GH-1113)."""

from __future__ import annotations

import pytest

from dev10x.skills.notifications import gchat_cards as mod


class TestMdToCardHtml:
    @pytest.mark.parametrize(
        ("markup", "expected"),
        [
            ("**strong**", "<b>strong</b>"),
            ("*strong*", "<b>strong</b>"),
            ("_soft_", "<i>soft</i>"),
            ("~gone~", "<s>gone</s>"),
            ("`fn()`", "<code>fn()</code>"),
            ("plain", "plain"),
        ],
    )
    def test_translates_inline_markup(self, markup: str, expected: str) -> None:
        assert mod.md_to_card_html(markup) == expected

    def test_leaves_intraword_punctuation_alone(self) -> None:
        assert mod.md_to_card_html("snake_case_name") == "snake_case_name"

    def test_escapes_html_special_characters(self) -> None:
        assert mod.md_to_card_html("a < b & c > d") == "a &lt; b &amp; c &gt; d"

    def test_does_not_reformat_inside_code_spans(self) -> None:
        assert mod.md_to_card_html("`*literal*`") == "<code>*literal*</code>"

    def test_escapes_html_inside_code_spans(self) -> None:
        assert mod.md_to_card_html("`<div>`") == "<code>&lt;div&gt;</code>"

    @pytest.mark.parametrize(
        "markup",
        [
            "[docs](https://example.com/a)",
            "<https://example.com/a|docs>",
        ],
    )
    def test_renders_both_link_syntaxes(self, markup: str) -> None:
        assert mod.md_to_card_html(markup) == '<a href="https://example.com/a">docs</a>'

    def test_renders_bare_link_using_url_as_label(self) -> None:
        assert (
            mod.md_to_card_html("<https://example.com>")
            == '<a href="https://example.com">https://example.com</a>'
        )

    def test_escapes_ampersand_in_link_href_once(self) -> None:
        rendered = mod.md_to_card_html("[q](https://example.com/?a=1&b=2)")
        assert rendered == '<a href="https://example.com/?a=1&amp;b=2">q</a>'

    def test_emphasis_does_not_leak_into_link_label(self) -> None:
        rendered = mod.md_to_card_html("[a_b_c](https://example.com)")
        assert rendered == '<a href="https://example.com">a_b_c</a>'

    def test_joins_lines_with_break_tags(self) -> None:
        assert mod.md_to_card_html("one\ntwo") == "one<br>two"

    def test_renders_bullet_list(self) -> None:
        assert mod.md_to_card_html("- a\n- b") == "<ul><li>a</li><li>b</li></ul>"

    def test_renders_numbered_list(self) -> None:
        assert mod.md_to_card_html("1. a\n2. b") == "<ol><li>a</li><li>b</li></ol>"

    def test_splits_adjacent_lists_of_different_kinds(self) -> None:
        assert mod.md_to_card_html("- a\n1. b") == "<ul><li>a</li></ul><br><ol><li>b</li></ol>"

    def test_applies_emphasis_inside_list_items(self) -> None:
        assert mod.md_to_card_html("- *hot*") == "<ul><li><b>hot</b></li></ul>"

    def test_closes_list_before_following_paragraph(self) -> None:
        assert mod.md_to_card_html("- a\ntail") == "<ul><li>a</li></ul><br>tail"

    def test_renders_quote_as_italic(self) -> None:
        assert mod.md_to_card_html("> quoted") == "<i>quoted</i>"

    def test_strips_sentinel_characters_from_input(self) -> None:
        assert mod.md_to_card_html("a\x000\x00b") == "a0b"


class TestPlainTextFallback:
    def test_drops_emphasis_markers(self) -> None:
        assert mod.plain_text_fallback("**bold** and _soft_") == "bold and soft"

    def test_reduces_links_to_their_label(self) -> None:
        assert mod.plain_text_fallback("[docs](https://example.com)") == "docs"
        assert mod.plain_text_fallback("<https://example.com|docs>") == "docs"

    def test_keeps_bare_link_url(self) -> None:
        assert mod.plain_text_fallback("<https://example.com>") == "https://example.com"

    def test_drops_code_span_backticks(self) -> None:
        assert mod.plain_text_fallback("`fn()`") == "fn()"

    def test_collapses_lists_and_quotes_into_one_line(self) -> None:
        assert mod.plain_text_fallback("- a\n2) b\n> c") == "a b c"


class TestWidgets:
    def test_text_paragraph_translates_markup(self) -> None:
        assert mod.text_paragraph("*hi*") == {"textParagraph": {"text": "<b>hi</b>"}}

    def test_text_paragraph_carries_max_lines(self) -> None:
        assert mod.text_paragraph("hi", max_lines=2)["textParagraph"]["maxLines"] == 2

    def test_divider_is_an_empty_widget(self) -> None:
        assert mod.divider() == {"divider": {}}

    def test_link_button_wraps_open_link_action(self) -> None:
        assert mod.link_button(text="Open", url="https://example.com") == {
            "text": "Open",
            "onClick": {"openLink": {"url": "https://example.com"}},
        }

    def test_button_list_wraps_buttons(self) -> None:
        button = mod.link_button(text="Open", url="https://example.com")
        assert mod.button_list([button]) == {"buttonList": {"buttons": [button]}}


class TestSection:
    def test_defaults_to_widgets_only(self) -> None:
        assert mod.section(widgets=[mod.divider()]) == {"widgets": [{"divider": {}}]}

    def test_includes_header_when_given(self) -> None:
        assert mod.section(widgets=[], header="Details")["header"] == "Details"

    def test_omits_collapse_keys_when_not_collapsible(self) -> None:
        built = mod.section(widgets=[], uncollapsible_widgets_count=1)
        assert "collapsible" not in built
        assert "uncollapsibleWidgetsCount" not in built

    def test_carries_collapse_configuration(self) -> None:
        built = mod.section(widgets=[], collapsible=True, uncollapsible_widgets_count=2)
        assert built["collapsible"] is True
        assert built["uncollapsibleWidgetsCount"] == 2

    def test_collapsible_without_count_omits_the_count(self) -> None:
        built = mod.section(widgets=[], collapsible=True)
        assert built["collapsible"] is True
        assert "uncollapsibleWidgetsCount" not in built


class TestCard:
    def test_omits_header_when_no_title(self) -> None:
        built = mod.card(card_id="c1", sections=[])
        assert built == {"cardId": "c1", "card": {"sections": []}}

    def test_builds_header_with_title_only(self) -> None:
        built = mod.card(card_id="c1", sections=[], title="Title")
        assert built["card"]["header"] == {"title": "Title"}

    def test_builds_full_header(self) -> None:
        built = mod.card(
            card_id="c1",
            sections=[],
            title="Title",
            subtitle="Sub",
            image_url="https://example.com/a.png",
            image_type="SQUARE",
        )
        assert built["card"]["header"] == {
            "title": "Title",
            "subtitle": "Sub",
            "imageUrl": "https://example.com/a.png",
            "imageType": "SQUARE",
        }

    def test_subtitle_without_title_is_dropped(self) -> None:
        built = mod.card(card_id="c1", sections=[], subtitle="Sub")
        assert "header" not in built["card"]


class TestSimpleCard:
    def test_wraps_body_in_one_section(self) -> None:
        built = mod.simple_card(card_id="c1", body="*hi*", title="T")
        assert built["cardId"] == "c1"
        assert built["card"]["header"]["title"] == "T"
        assert built["card"]["sections"] == [
            {"widgets": [{"textParagraph": {"text": "<b>hi</b>"}}]}
        ]

    def test_appends_buttons_when_given(self) -> None:
        button = mod.link_button(text="Open", url="https://example.com")
        built = mod.simple_card(card_id="c1", body="hi", buttons=[button])
        widgets = built["card"]["sections"][0]["widgets"]
        assert widgets[-1] == {"buttonList": {"buttons": [button]}}

    def test_empty_button_list_adds_no_widget(self) -> None:
        built = mod.simple_card(card_id="c1", body="hi", buttons=[])
        assert len(built["card"]["sections"][0]["widgets"]) == 1
