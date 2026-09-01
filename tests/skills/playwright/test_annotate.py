"""Tests for the shared Playwright annotation module (GH-1087, GH-1086).

The module exists so the overlay is code rather than documentation —
these tests pin the three properties whose absence shipped broken
recordings: navigation-surviving install, argument-passed caption text,
and a pointer that refuses an absent target.

Playwright is not installed here; the fakes below stand in for the page,
context and locator objects the module touches.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parent.parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "annotate",
    _repo_root / "skills" / "playwright" / "lib" / "annotate.py",
)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
# Registered before exec because `@dataclass` resolves annotations
# through `sys.modules[cls.__module__]`, which is how a generated script
# importing this off `DEV10X_PLAYWRIGHT_LIB` loads it anyway.
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)


class FakeContext:
    def __init__(self) -> None:
        self.init_scripts: list[str] = []

    def add_init_script(self, script: str) -> None:
        self.init_scripts.append(script)


class FakeMouse:
    def __init__(self) -> None:
        self.moves: list[tuple[float, float, int]] = []

    def move(self, x: float, y: float, steps: int = 1) -> None:
        self.moves.append((x, y, steps))


VIEWPORT = {"width": 1680, "height": 1050}


class FakePage:
    def __init__(self, viewport: dict[str, int] | None = None) -> None:
        self.context = FakeContext()
        self.mouse = FakeMouse()
        self.evaluated: list[tuple[str, object]] = []
        self.viewport_size = VIEWPORT if viewport is None else viewport
        self.screenshots: list[dict[str, object]] = []
        self.url = "https://staging-app.example.com/pos"

    def evaluate(self, script: str, arg: object = None) -> None:
        self.evaluated.append((script, arg))

    def screenshot(self, **kwargs: object) -> None:
        self.screenshots.append(kwargs)


class FakeLocator:
    def __init__(self, box: dict[str, float] | None) -> None:
        self._box = box
        self.scrolled = False
        self.clicked = False

    def bounding_box(self) -> dict[str, float] | None:
        return self._box

    def scroll_into_view_if_needed(self) -> None:
        self.scrolled = True

    def click(self) -> None:
        self.clicked = True

    def screenshot(self) -> bytes:
        return b"\x89PNG-crop"

    def __repr__(self) -> str:
        return "Locator@get_by_text('Amount due')"


def on_screen() -> FakeLocator:
    return FakeLocator({"x": 100, "y": 200, "width": 300, "height": 40})


def below_the_fold() -> FakeLocator:
    """A perfectly good bounding box, ~200px under the viewport."""
    return FakeLocator({"x": 100, "y": 1250, "width": 300, "height": 40})


def caption_dwell(text: str) -> int:
    return _mod.caption_dwell_ms(text)


@pytest.fixture
def page() -> FakePage:
    return FakePage()


@pytest.fixture
def anno(page: FakePage):
    return _mod.Annotator(page)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(_mod.time, "sleep", lambda seconds: None)


class TestOverlayScript:
    def test_palette_placeholders_are_resolved(self):
        script = _mod.overlay_script()
        assert "__POINTER_COLOR__" not in script
        assert _mod.POINTER_COLOR in script

    def test_caption_is_set_as_text_not_markup(self):
        assert "textContent" in _mod.overlay_script()
        assert "innerHTML = text" not in _mod.overlay_script()

    def test_caption_flips_away_from_a_pointer_in_the_lower_third(self):
        script = _mod.overlay_script()
        assert "placeCaption" in script
        # The pointer's y is recorded so the caption can move off it.
        assert "state.pointerY = y" in script
        assert "h * (2 / 3)" in script


class TestOverlayJavaScriptParses:
    """The overlay is JS embedded in Python — nothing else type-checks it.

    A syntax error here uninstalls the entire overlay at runtime and the
    capture run still passes, which is the exact failure mode this module
    was created to end (GH-1087). `node --check` is the only thing in
    reach that actually parses it.
    """

    @staticmethod
    def _check(source: str, tmp_path: Path) -> None:
        node = shutil.which("node")
        if node is None:
            pytest.skip("node is not installed")
        script = tmp_path / "overlay.js"
        script.write_text(source, encoding="utf-8")
        result = subprocess.run(
            [node, "--check", str(script)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr

    def test_overlay_script_parses(self, tmp_path):
        self._check(_mod.overlay_script(), tmp_path)

    def test_redaction_script_parses_with_hostile_selectors(self, tmp_path):
        source = _mod.redaction_script(
            ["#a", "[data-test='he said \"hi\"']", "</script><img src=x>", "a\\b`c"],
            [{"x": 0, "y": 0, "width": 400, "height": 60}],
        )
        self._check(source, tmp_path)


class TestCaptionDwell:
    def test_dwell_grows_with_caption_length(self):
        assert _mod.caption_dwell_ms("a" * 20) > _mod.caption_dwell_ms("a")

    def test_short_caption_gets_the_base_dwell(self):
        assert _mod.caption_dwell_ms("") == _mod.CAPTION_BASE_MS

    def test_long_caption_is_capped(self):
        assert _mod.caption_dwell_ms("a" * 500) == _mod.CAPTION_MAX_MS


class TestTargetCenter:
    def test_returns_the_box_centre(self):
        assert _mod.target_center({"x": 10, "y": 20, "width": 40, "height": 10}) == (30, 25)

    def test_absent_box_raises_rather_than_pointing_approximately(self):
        with pytest.raises(ValueError, match="no bounding box"):
            _mod.target_center(None)


class TestAssertInViewport:
    def test_on_screen_box_passes(self):
        _mod.assert_in_viewport({"x": 10, "y": 20, "width": 40, "height": 10}, VIEWPORT)

    def test_absent_box_still_raises(self):
        with pytest.raises(ValueError, match="no bounding box"):
            _mod.assert_in_viewport(None, VIEWPORT)

    @pytest.mark.parametrize(
        "box",
        [
            {"x": 100, "y": 1250, "width": 300, "height": 40},  # below the fold
            {"x": 100, "y": -80, "width": 300, "height": 40},  # scrolled above
            {"x": 1700, "y": 200, "width": 300, "height": 40},  # off to the right
            {"x": -400, "y": 200, "width": 300, "height": 40},  # off to the left
        ],
    )
    def test_laid_out_but_off_screen_box_raises(self, box):
        with pytest.raises(ValueError, match="outside the viewport"):
            _mod.assert_in_viewport(box, VIEWPORT)

    def test_partly_visible_box_is_accepted(self):
        _mod.assert_in_viewport({"x": 100, "y": 1040, "width": 300, "height": 40}, VIEWPORT)

    def test_absent_viewport_disables_the_check(self):
        _mod.assert_in_viewport({"x": 100, "y": 9999, "width": 300, "height": 40}, None)


class TestInstall:
    def test_registers_an_init_script_so_the_overlay_survives_navigation(self, anno, page):
        anno.install()
        assert len(page.context.init_scripts) == 1

    def test_also_installs_into_the_already_loaded_document(self, anno, page):
        anno.install()
        assert page.evaluated[0][0] == page.context.init_scripts[0]


class TestSay:
    def test_caption_text_is_passed_as_an_argument_not_interpolated(self, anno, page):
        hostile = "he said `hi`\n</script> 'quoted'"
        anno.say(hostile)
        script, arg = page.evaluated[-1]
        assert arg == [hostile, _mod.caption_dwell_ms(hostile), None, "claim"]
        assert hostile not in script

    def test_dwell_is_derived_from_the_caption(self, anno, page):
        anno.say("short")
        assert page.evaluated[-1][1][1] == _mod.caption_dwell_ms("short")


class TestPointAt:
    def test_moves_the_overlay_and_the_real_mouse_to_the_target(self, anno, page):
        anno.point_at(FakeLocator({"x": 0, "y": 0, "width": 100, "height": 50}))
        assert page.evaluated[-1][1] == [50, 25]
        assert page.mouse.moves == [(50, 25, _mod.CURSOR_MOVE_STEPS)]

    def test_detached_target_raises(self, anno):
        with pytest.raises(ValueError, match="no bounding box"):
            anno.point_at(FakeLocator(None))

    def test_scrolls_before_measuring_like_click_always_has(self, anno):
        locator = on_screen()
        anno.point_at(locator)
        assert locator.scrolled is True

    def test_target_still_below_the_fold_after_scrolling_raises(self, anno):
        with pytest.raises(ValueError, match="outside the viewport"):
            anno.point_at(below_the_fold())

    def test_settle_reads_the_module_constant_at_call_time(self, page, monkeypatch):
        slept: list[float] = []
        monkeypatch.setattr(_mod.time, "sleep", slept.append)
        monkeypatch.setattr(_mod, "POINT_SETTLE_SECONDS", 9.0)
        _mod.Annotator(page).point_at(on_screen())
        assert 9.0 in slept


class TestPace:
    def test_scales_the_derived_caption_dwell(self, page):
        _mod.Annotator(page, pace=2.0).say("hello")
        assert page.evaluated[-1][1][1] == caption_dwell("hello") * 2

    def test_scales_the_pointer_settle(self, page, monkeypatch):
        slept: list[float] = []
        monkeypatch.setattr(_mod.time, "sleep", slept.append)
        _mod.Annotator(page, pace=2.0).point_at(on_screen())
        assert _mod.POINT_SETTLE_SECONDS * 2 in slept

    def test_defaults_to_unscaled(self, anno, page):
        assert anno.pace == 1.0
        anno.say("hello")
        assert page.evaluated[-1][1][1] == caption_dwell("hello")


class TestClick:
    def test_points_then_narrates_then_acts(self, anno, page):
        locator = FakeLocator({"x": 0, "y": 0, "width": 10, "height": 10})
        anno.click(locator, announce="Choosing the customer")

        kinds = ["point" if arg == [5, 5] else "caption" for _, arg in page.evaluated]
        assert kinds == ["point", "caption"]
        assert locator.scrolled is True
        assert locator.clicked is True

    def test_announce_is_optional(self, anno, page):
        locator = FakeLocator({"x": 0, "y": 0, "width": 10, "height": 10})
        anno.click(locator)
        assert len(page.evaluated) == 1
        assert locator.clicked is True


class TestTap:
    def test_narrates_acts_then_captions_the_outcome(self, anno, page):
        locator = on_screen()
        anno.tap(locator, announce="Declining the tyre", then="It leaves the bill")
        captions = [
            arg[0]
            for _, arg in page.evaluated
            if isinstance(arg, list) and isinstance(arg[0], str)
        ]
        assert captions == ["Declining the tyre", "It leaves the bill"]
        assert locator.clicked is True

    def test_holds_a_beat_after_acting(self, page, monkeypatch):
        slept: list[float] = []
        monkeypatch.setattr(_mod.time, "sleep", slept.append)
        _mod.Annotator(page).tap(on_screen())
        assert _mod.BEAT_SECONDS in slept


class TestShootManifest:
    def test_records_file_target_and_claim(self, anno):
        row = anno.shoot(on_screen(), "/tmp/x/total.png", claim="The oil job is billed")
        assert row == {
            "file": "total.png",
            "target": "Locator@get_by_text('Amount due')",
            "claim": "The oil job is billed",
        }

    def test_uses_the_locator_repr_not_an_author_written_label(self, anno):
        anno.shoot(on_screen(), "/tmp/x/a.png", claim="c")
        assert anno.manifest[0]["target"] == repr(on_screen())

    def test_refuses_to_shoot_an_off_screen_subject(self, anno):
        with pytest.raises(ValueError, match="outside the viewport"):
            anno.shoot(below_the_fold(), "/tmp/x/a.png", claim="c")
        assert anno.manifest == []

    def test_rows_render_as_file_target_claim(self, anno):
        anno.shoot(on_screen(), "/tmp/x/a.png", claim="The oil job is billed")
        assert anno.manifest_rows() == [
            "a.png → Locator@get_by_text('Amount due') → The oil job is billed"
        ]

    def test_manifest_is_a_copy_callers_cannot_mutate(self, anno):
        anno.shoot(on_screen(), "/tmp/x/a.png", claim="c")
        anno.manifest.clear()
        assert len(anno.manifest) == 1


class TestTheme:
    def test_default_palette_clears_wcag_aa_on_its_own_surface(self):
        _mod.DEFAULT_THEME.assert_readable()

    @pytest.mark.parametrize("token", ["on_surface", "accent", "absence"])
    def test_every_text_token_is_measured_not_assumed(self, token):
        ratio = _mod.contrast_ratio(getattr(_mod.DEFAULT_THEME, token), _mod.DEFAULT_THEME.surface)
        assert ratio >= 4.5

    def test_a_low_contrast_override_is_refused_at_construction(self, page):
        washed_out = _mod.Theme(surface="#0c0e14", on_surface="#1a1d26")
        with pytest.raises(ValueError, match="below the 4.5:1 floor"):
            _mod.Annotator(page, theme=washed_out)

    def test_does_not_inherit_the_source_brand_orange(self):
        # The source author's own guidelines name this exact literal as
        # the example of a colour never to hardcode (GH-1126).
        assert "#fc7d12" not in _mod.overlay_script()

    def test_overlay_takes_its_colours_from_the_theme(self):
        script = _mod.overlay_script(_mod.Theme(accent="#00ccff"))
        assert "#00ccff" in script
        assert "__ACCENT__" not in script

    def test_contrast_ratio_is_symmetric(self):
        assert _mod.contrast_ratio("#ffffff", "#000000") == pytest.approx(21.0)
        assert _mod.contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0)

    def test_malformed_colour_raises(self):
        with pytest.raises(ValueError, match="expected #rrggbb"):
            _mod.contrast_ratio("#fff", "#000000")


class TestTwoTierCaption:
    def test_sub_line_is_passed_as_an_argument_not_markup(self, anno, page):
        anno.say("Surface 1 of 3", sub="The vehicle carries over untouched")
        script, arg = page.evaluated[-1]
        assert arg[0] == "Surface 1 of 3"
        assert arg[2] == "The vehicle carries over untouched"
        assert "The vehicle" not in script

    def test_dwell_derives_from_both_lines_not_just_the_title(self, anno, page):
        anno.say("Short", sub="a" * 60)
        assert page.evaluated[-1][1][1] == _mod.caption_dwell_ms("Short", "a" * 60)
        assert _mod.caption_dwell_ms("Short", "a" * 60) > _mod.caption_dwell_ms("Short")

    def test_absence_captions_are_marked_as_a_distinct_kind(self, anno, page):
        anno.say("The tech's copy is not shown — Print blocks capture", kind="absence")
        assert page.evaluated[-1][1][3] == "absence"

    def test_absence_renders_differently_from_a_claim(self):
        assert "kind === 'absence'" in _mod.overlay_script()


class TestCard:
    def test_lines_are_passed_as_an_argument_not_interpolated(self, anno, page):
        lines = ["Recorded on staging", "Fixture data — `not` production"]
        anno.card(lines)
        script, arg = page.evaluated[-2]
        assert arg == lines
        assert "Fixture data" not in script

    def test_dwell_allows_over_a_second_per_line(self):
        assert _mod.card_dwell_ms(["a"] * 8) == pytest.approx(11000, abs=1500)
        assert _mod.card_dwell_ms(["a"] * 5) == pytest.approx(8000, abs=1500)

    def test_short_card_still_gets_a_readable_floor(self):
        assert _mod.card_dwell_ms(["one"]) == _mod.CARD_MIN_MS

    def test_card_is_removed_after_its_dwell(self, anno, page):
        anno.card(["one"])
        assert "clearCard" in page.evaluated[-1][0]

    def test_survives_a_body_rerender_by_attaching_to_documentelement(self):
        assert "documentElement.appendChild(el)" in _mod.overlay_script()

    def test_uses_textcontent_for_every_caller_supplied_line(self):
        script = _mod.overlay_script()
        assert "row.textContent = line" in script
        assert "el.innerHTML" not in script


class TestRedaction:
    def test_reapplies_through_an_init_script_not_just_evaluate(self, page):
        anno = _mod.Annotator(page, redact=["#customer-name"])
        anno.install()
        assert any("__dxAnnotate.redact" in s for s in page.context.init_scripts)

    def test_a_mask_added_later_also_survives_navigation(self, anno, page):
        anno.install()
        before = len(page.context.init_scripts)
        anno.redact(".phone")
        assert len(page.context.init_scripts) == before + 1
        assert ".phone" in page.context.init_scripts[-1]

    def test_regions_cover_fixed_chrome(self, anno, page):
        anno.redact_region(0, 0, 400, 60)
        script = page.context.init_scripts[-1]
        assert '"width": 400' in script or '"width":400' in script

    def test_selector_is_json_encoded_not_string_concatenated(self, anno, page):
        anno.redact("[data-test='he said \"hi\"']")
        script = page.context.init_scripts[-1]
        # Valid JS: the embedded quotes are escaped rather than closing
        # the literal early.
        assert '\\"hi\\"' in script

    def test_angle_brackets_cannot_terminate_a_surrounding_element(self, anno, page):
        anno.redact("</script><img src=x>")
        assert "</script>" not in page.context.init_scripts[-1]
        assert "\\u003c" in page.context.init_scripts[-1]

    def test_masks_are_opaque_never_blurred(self):
        script = _mod.overlay_script()
        assert "filter: blur" not in script
        assert "filter:blur" not in script
        assert "backdrop-filter" not in script
        assert "background:' + REDACTION" in script

    def test_masks_are_re_measured_rather_than_positioned_once(self):
        assert "setInterval(paintRedactions" in _mod.overlay_script()

    def test_repeated_registrations_do_not_stack_duplicate_masks(self):
        # Each redact() re-registers the whole list, so a new document
        # replays every registration.
        assert "seen.has(key(item))" in _mod.overlay_script()

    def test_no_masks_means_no_redaction_script(self, anno, page):
        anno.install()
        assert not any("__dxAnnotate.redact" in s for s in page.context.init_scripts)


class TestStepChipAndChapters:
    def test_chip_shows_position_and_title(self, anno, page):
        anno.step(3, 4, "The decline survives the conversion")
        assert page.evaluated[-1][1] == "3 of 4 — The decline survives the conversion"

    def test_offsets_are_measured_against_the_recording_start(self, anno, monkeypatch):
        clock = iter([100.0, 105.0, 232.5])
        monkeypatch.setattr(_mod.time, "monotonic", lambda: next(clock))
        anno.mark_video_start()
        anno.step(1, 2, "Opening the estimate")
        anno.step(2, 2, "Approving converts it")
        assert [c["timestamp"] for c in anno.chapters()] == ["0:05", "2:12"]

    def test_chapter_lines_are_ready_for_a_description(self, anno, monkeypatch):
        clock = iter([0.0, 105.0])
        monkeypatch.setattr(_mod.time, "monotonic", lambda: next(clock))
        anno.mark_video_start()
        anno.step(1, 1, "Approving converts the estimate")
        assert anno.chapter_lines() == ["1:45 Approving converts the estimate"]

    def test_unanchored_chapters_raise_rather_than_fabricate_precision(self, anno):
        anno.step(1, 2, "Opening the estimate")
        with pytest.raises(ValueError, match="unanchored"):
            anno.chapters()

    def test_long_recordings_get_an_hour_field(self):
        assert _mod.format_timestamp(3725) == "1:02:05"


class TestHighlight:
    def test_outlines_the_element_being_read(self, anno, page):
        anno.highlight(on_screen())
        script, arg = page.evaluated[-1]
        assert "highlight" in script
        assert arg == {"x": 100, "y": 200, "width": 300, "height": 40}

    def test_refuses_an_element_that_is_off_screen(self, anno):
        with pytest.raises(ValueError, match="outside the viewport"):
            anno.highlight(below_the_fold())

    def test_composes_with_the_pointer_rather_than_replacing_it(self):
        script = _mod.overlay_script()
        # The highlight sits below the pointer's z-index, so both show.
        assert "'z-index: 2147483645'" in script
        assert "'z-index: ' + TOP" in script


class TestCompareAndZoom:
    def test_before_crop_is_pinned_beside_the_live_element(self, anno, page):
        locator = on_screen()
        before = anno.capture_region(locator)
        anno.compare(locator, before, caption="Declining removes it from the bill")
        insets = [arg for script, arg in page.evaluated if "inset(" in script]
        assert insets[-1][2] == "Before"
        assert insets[-1][0].startswith("data:image/png;base64,")

    def test_the_caption_still_says_why_it_matters(self, anno, page):
        locator = on_screen()
        anno.compare(locator, b"png", caption="Declining removes it from the bill")
        captions = [
            arg for _, arg in page.evaluated if isinstance(arg, list) and isinstance(arg[0], str)
        ]
        assert captions[-1][0] == "Declining removes it from the bill"

    def test_the_inset_is_cleared_afterwards(self, anno, page):
        anno.compare(on_screen(), b"png", caption="c")
        assert "clearInsets" in page.evaluated[-1][0]

    def test_zoom_magnifies_beside_the_element_keeping_page_context(self, anno, page):
        anno.zoom(on_screen(), factor=3.0)
        insets = [arg for script, arg in page.evaluated if "inset(" in script]
        assert insets[-1][2] == "Detail"
        assert insets[-1][3] == 3.0

    def test_zoom_refuses_an_off_screen_target(self, anno):
        with pytest.raises(ValueError, match="outside the viewport"):
            anno.zoom(below_the_fold())


class TestDebugDump:
    def test_reports_url_screenshot_and_sorted_button_names(self, page, tmp_path, monkeypatch):
        monkeypatch.setattr(
            page, "evaluate", lambda script, arg=None: ["Save", "add customer", ""]
        )
        report = _mod.debug_dump(page, "open-wo", out_dir=str(tmp_path))
        assert report["url"] == page.url
        assert report["screenshot"] == str(tmp_path / "open-wo.png")
        assert report["buttons"] == ["Save", "add customer"]

    def test_captures_the_whole_page_not_just_the_viewport(self, page, tmp_path, monkeypatch):
        monkeypatch.setattr(page, "evaluate", lambda script, arg=None: [])
        _mod.debug_dump(page, "t", out_dir=str(tmp_path))
        assert page.screenshots[0]["full_page"] is True
