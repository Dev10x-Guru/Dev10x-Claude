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
from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parent.parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "annotate",
    _repo_root / "skills" / "playwright" / "lib" / "annotate.py",
)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
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
        assert arg == [hostile, _mod.caption_dwell_ms(hostile)]
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
