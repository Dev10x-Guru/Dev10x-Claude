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


class FakePage:
    def __init__(self) -> None:
        self.context = FakeContext()
        self.mouse = FakeMouse()
        self.evaluated: list[tuple[str, object]] = []

    def evaluate(self, script: str, arg: object = None) -> None:
        self.evaluated.append((script, arg))


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

    def test_offscreen_target_raises(self, anno):
        with pytest.raises(ValueError):
            anno.point_at(FakeLocator(None))


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
