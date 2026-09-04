"""Tests for the QA evidence verifier (GH-1086).

Loads the uv-script via importlib and exercises the pure helpers —
stddev normalisation, frame sampling, kind classification and report
aggregation — without invoking ImageMagick or ffmpeg.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parent.parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "verify_evidence",
    _repo_root / "skills" / "qa-self" / "scripts" / "verify-evidence.py",
)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


class TestParseStddev:
    def test_normalised_value_passes_through(self):
        assert _mod.parse_stddev("0.1834\n") == pytest.approx(0.1834)

    def test_quantum_scaled_value_is_rescaled(self):
        assert _mod.parse_stddev("6553.5") == pytest.approx(0.1)

    def test_uniform_image_reads_as_zero(self):
        assert _mod.parse_stddev("0") == 0.0

    def test_trailing_tokens_are_ignored(self):
        assert _mod.parse_stddev("0.42 (0.42)") == pytest.approx(0.42)


class TestFrameTimestamps:
    def test_samples_three_points_through_the_recording(self):
        assert _mod.frame_timestamps(40.0) == [10.0, 20.0, 30.0]

    def test_zero_duration_yields_no_samples(self):
        assert _mod.frame_timestamps(0.0) == []

    def test_negative_duration_yields_no_samples(self):
        assert _mod.frame_timestamps(-1.0) == []


class TestClassify:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("shot.png", "screenshot"),
            ("shot.PNG", "screenshot"),
            ("shot.jpg", "screenshot"),
            ("shot.jpeg", "screenshot"),
            ("clip.webm", "video"),
            ("clip.mp4", "video"),
        ],
    )
    def test_infers_kind_from_extension(self, name, expected):
        assert _mod.classify("auto", Path(name)) == expected

    def test_explicit_kind_overrides_extension(self):
        assert _mod.classify("video", Path("frame.png")) == "video"

    def test_unknown_extension_raises(self):
        with pytest.raises(_mod.ToolingError):
            _mod.classify("auto", Path("evidence.txt"))


class TestVerifyMissingFile:
    def test_absent_file_fails_without_invoking_tooling(self, tmp_path):
        result = _mod.verify(tmp_path / "nope.png", kind="auto", min_stddev=0.02)
        assert result["ok"] is False
        assert result["failures"] == ["file does not exist"]


class TestBuildReport:
    def test_all_passing_reports_ok(self):
        report = _mod.build_report([{"ok": True}, {"ok": True}])
        assert report == {"ok": True, "checked": 2, "failed": 0, "artifacts": [{"ok": True}] * 2}

    def test_one_failure_fails_the_whole_report(self):
        report = _mod.build_report([{"ok": True}, {"ok": False}])
        assert report["ok"] is False
        assert report["failed"] == 1

    def test_empty_input_reports_ok(self):
        assert _mod.build_report([])["ok"] is True


class TestVerifyScreenshot:
    def _write(self, tmp_path: Path, *, size: int) -> Path:
        path = tmp_path / "shot.png"
        path.write_bytes(b"\x00" * size)
        return path

    def test_flags_a_file_below_the_size_floor(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_mod, "image_stddev", lambda path: 0.5)
        result = _mod.verify_screenshot(
            self._write(tmp_path, size=200), min_bytes=10_000, min_stddev=0.02
        )
        assert result["ok"] is False
        assert "below the 10000-byte floor" in result["failures"][0]

    def test_flags_a_uniform_frame(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_mod, "image_stddev", lambda path: 0.0)
        result = _mod.verify_screenshot(
            self._write(tmp_path, size=50_000), min_bytes=10_000, min_stddev=0.02
        )
        assert result["ok"] is False
        assert "uniform" in result["failures"][0]

    def test_passes_a_real_looking_screenshot(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_mod, "image_stddev", lambda path: 0.21)
        result = _mod.verify_screenshot(
            self._write(tmp_path, size=120_000), min_bytes=10_000, min_stddev=0.02
        )
        assert result["ok"] is True
        assert result["failures"] == []


class TestSizeFloorFailures:
    def test_a_file_at_the_floor_passes(self):
        assert _mod.size_floor_failures(10_000, 10_000) == []

    def test_a_file_below_the_floor_reports_both_numbers(self):
        (failure,) = _mod.size_floor_failures(200, 10_000)
        assert "200 bytes" in failure
        assert "10000-byte floor" in failure


class TestVerifyVideo:
    @pytest.fixture(autouse=True)
    def _skip_border_check(self, monkeypatch):
        """These cases stub ``extract_frame`` to a no-op, so no real PNG
        exists for the border check to measure. Padding is covered on its
        own in ``TestVerifyVideoBorderCheck``."""
        monkeypatch.setattr(_mod, "flat_border_edges", lambda path, *, max_stddev: {})

    def _write(self, tmp_path: Path, *, size: int) -> Path:
        path = tmp_path / "clip.webm"
        path.write_bytes(b"\x00" * size)
        return path

    def test_flags_a_recording_with_no_duration(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_mod, "video_duration", lambda path: 0.0)
        result = _mod.verify_video(
            self._write(tmp_path, size=500_000), min_bytes=50_000, min_stddev=0.02
        )
        assert result["ok"] is False
        assert "never flushed" in result["failures"][0]

    def test_flags_a_recording_whose_every_frame_is_uniform(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_mod, "video_duration", lambda path: 30.0)
        monkeypatch.setattr(_mod, "extract_frame", lambda path, *, offset, dest: None)
        monkeypatch.setattr(_mod, "image_stddev", lambda path: 0.001)
        result = _mod.verify_video(
            self._write(tmp_path, size=500_000), min_bytes=50_000, min_stddev=0.02
        )
        assert result["ok"] is False
        assert "every sampled frame is uniform" in result["failures"][0]

    def test_one_non_uniform_frame_is_enough_to_pass(self, tmp_path, monkeypatch):
        stddevs = iter([0.0, 0.3, 0.0])
        monkeypatch.setattr(_mod, "video_duration", lambda path: 30.0)
        monkeypatch.setattr(_mod, "extract_frame", lambda path, *, offset, dest: None)
        monkeypatch.setattr(_mod, "image_stddev", lambda path: next(stddevs))
        result = _mod.verify_video(
            self._write(tmp_path, size=500_000), min_bytes=50_000, min_stddev=0.02
        )
        assert result["ok"] is True
        assert [frame["at"] for frame in result["frames"]] == [7.5, 15.0, 22.5]

    def test_saved_frames_survive_and_are_reported(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_mod, "video_duration", lambda path: 30.0)
        monkeypatch.setattr(
            _mod, "extract_frame", lambda path, *, offset, dest: dest.write_bytes(b"png")
        )
        monkeypatch.setattr(_mod, "image_stddev", lambda path: 0.3)
        frames_dir = tmp_path / "review-frames"

        result = _mod.verify_video(
            self._write(tmp_path, size=500_000),
            min_bytes=50_000,
            min_stddev=0.02,
            save_frames=frames_dir,
        )

        saved = [Path(frame["path"]) for frame in result["frames"]]
        assert len(saved) == 3
        assert all(path.exists() for path in saved)

    def test_frames_are_discarded_when_no_destination_is_given(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_mod, "video_duration", lambda path: 30.0)
        monkeypatch.setattr(
            _mod, "extract_frame", lambda path, *, offset, dest: dest.write_bytes(b"png")
        )
        monkeypatch.setattr(_mod, "image_stddev", lambda path: 0.3)

        result = _mod.verify_video(
            self._write(tmp_path, size=500_000), min_bytes=50_000, min_stddev=0.02
        )

        assert all("path" not in frame for frame in result["frames"])

    def test_size_floor_still_applies_to_a_watchable_recording(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_mod, "video_duration", lambda path: 30.0)
        monkeypatch.setattr(_mod, "extract_frame", lambda path, *, offset, dest: None)
        monkeypatch.setattr(_mod, "image_stddev", lambda path: 0.3)
        result = _mod.verify_video(
            self._write(tmp_path, size=1_000), min_bytes=50_000, min_stddev=0.02
        )
        assert result["ok"] is False


class TestImageSize:
    def test_parses_identify_output(self, monkeypatch):
        monkeypatch.setattr(_mod, "_run", lambda argv: "1920 1080\n")
        assert _mod.image_size(Path("f.png")) == (1920, 1080)

    @pytest.mark.parametrize("raw", ["", "1920", "wide tall"])
    def test_unparseable_output_raises(self, monkeypatch, raw):
        monkeypatch.setattr(_mod, "_run", lambda argv: raw)
        with pytest.raises(_mod.ToolingError):
            _mod.image_size(Path("f.png"))


class TestRegionStats:
    def test_returns_stddev_and_mean(self, monkeypatch):
        monkeypatch.setattr(_mod, "_run", lambda argv: "0.0 0.494\n")
        assert _mod.region_stats(Path("f.png"), geometry="6x1080+1914+0") == (0.0, 0.494)

    def test_crops_on_read_rather_than_writing_a_temp_file(self, monkeypatch):
        seen: list[str] = []

        def record(argv):
            seen.append(argv[-1])
            return "0.1 0.5"

        monkeypatch.setattr(_mod, "_run", record)
        _mod.region_stats(Path("f.png"), geometry="6x1080+1914+0")
        assert seen == ["f.png[6x1080+1914+0]"]

    def test_short_output_raises(self, monkeypatch):
        monkeypatch.setattr(_mod, "_run", lambda argv: "0.1")
        with pytest.raises(_mod.ToolingError):
            _mod.region_stats(Path("f.png"), geometry="6x6+0+0")


class TestBorderGeometries:
    def test_samples_only_the_right_and_bottom_edges(self):
        assert _mod.border_geometries(1920, 1080, strip=6) == {
            "right": "6x1080+1914+0",
            "bottom": "1920x6+0+1074",
        }

    def test_an_axis_narrower_than_the_strip_is_skipped(self):
        assert _mod.border_geometries(4, 1080, strip=6) == {"bottom": "4x6+0+1074"}


class TestFlatBorderEdges:
    def _stub(self, monkeypatch, *, stats: dict[str, tuple[float, float]]):
        monkeypatch.setattr(_mod, "image_size", lambda path: (1920, 1080))
        geometries = _mod.border_geometries(1920, 1080)
        by_geometry = {geometries[edge]: value for edge, value in stats.items()}
        monkeypatch.setattr(_mod, "region_stats", lambda path, *, geometry: by_geometry[geometry])

    def test_a_full_bleed_frame_reports_no_flat_edges(self, monkeypatch):
        self._stub(monkeypatch, stats={"right": (0.19, 0.87), "bottom": (0.22, 0.84)})
        assert _mod.flat_border_edges(Path("f.png"), max_stddev=0.005) == {}

    def test_a_padded_frame_reports_the_padded_edges_with_their_grey(self, monkeypatch):
        self._stub(monkeypatch, stats={"right": (0.0, 0.494), "bottom": (0.0, 0.494)})
        flat = _mod.flat_border_edges(Path("f.png"), max_stddev=0.005)
        assert sorted(flat) == ["bottom", "right"]
        assert flat["right"] == {"stddev": 0.0, "mean": 0.494}

    def test_padding_on_one_axis_only_is_still_caught(self, monkeypatch):
        self._stub(monkeypatch, stats={"right": (0.0, 0.494), "bottom": (0.21, 0.84)})
        assert list(_mod.flat_border_edges(Path("f.png"), max_stddev=0.005)) == ["right"]


class TestPaddedEdgeFailures:
    def test_an_edge_flat_in_every_frame_fails(self):
        frames = [{"flat_edges": {"right": {}}} for _ in range(3)]
        (failure,) = _mod.padded_edge_failures(frames)
        assert "right edge" in failure
        assert "record_video_size" in failure

    def test_an_edge_flat_in_only_some_frames_is_tolerated(self):
        frames = [{"flat_edges": {"right": {}}}, {"flat_edges": {}}, {"flat_edges": {}}]
        assert _mod.padded_edge_failures(frames) == []

    def test_both_padded_axes_are_named_in_one_failure(self):
        frames = [{"flat_edges": {"right": {}, "bottom": {}}} for _ in range(3)]
        (failure,) = _mod.padded_edge_failures(frames)
        assert failure.startswith("bottom, right edge")

    def test_frames_without_border_data_are_not_judged(self):
        assert _mod.padded_edge_failures([{"at": 1.0}, {"at": 2.0}]) == []

    def test_no_frames_yields_no_failure(self):
        assert _mod.padded_edge_failures([]) == []


class TestVerifyVideoBorderCheck:
    def _prepare(self, tmp_path, monkeypatch, *, flat_edges: dict):
        path = tmp_path / "clip.webm"
        path.write_bytes(b"\x00" * 500_000)
        monkeypatch.setattr(_mod, "video_duration", lambda path: 30.0)
        monkeypatch.setattr(_mod, "extract_frame", lambda path, *, offset, dest: None)
        monkeypatch.setattr(_mod, "image_stddev", lambda path: 0.3)
        monkeypatch.setattr(
            _mod, "flat_border_edges", lambda path, *, max_stddev: dict(flat_edges)
        )
        return path

    def test_a_padded_recording_fails(self, tmp_path, monkeypatch):
        path = self._prepare(tmp_path, monkeypatch, flat_edges={"right": {"mean": 0.494}})
        result = _mod.verify_video(path, min_bytes=50_000, min_stddev=0.02)
        assert result["ok"] is False
        assert "padded" in result["failures"][0]

    def test_a_full_bleed_recording_passes(self, tmp_path, monkeypatch):
        path = self._prepare(tmp_path, monkeypatch, flat_edges={})
        result = _mod.verify_video(path, min_bytes=50_000, min_stddev=0.02)
        assert result["ok"] is True

    def test_the_check_can_be_disabled(self, tmp_path, monkeypatch):
        path = self._prepare(tmp_path, monkeypatch, flat_edges={"right": {"mean": 0.494}})
        result = _mod.verify_video(path, min_bytes=50_000, min_stddev=0.02, border_max_stddev=None)
        assert result["ok"] is True
        assert all("flat_edges" not in frame for frame in result["frames"])

    def test_a_uniform_recording_reports_only_the_uniformity_failure(self, tmp_path, monkeypatch):
        path = self._prepare(tmp_path, monkeypatch, flat_edges={"right": {"mean": 0.494}})
        monkeypatch.setattr(_mod, "image_stddev", lambda path: 0.001)
        result = _mod.verify_video(path, min_bytes=50_000, min_stddev=0.02)
        assert result["failures"] == ["every sampled frame is uniform (max stddev 0.0010 < 0.02)"]


class TestMain:
    def test_reports_tooling_error_as_json_on_stdout(self, tmp_path, capsys):
        target = tmp_path / "evidence.txt"
        target.write_text("not an artifact")
        assert _mod.main([str(target)]) == 2
        assert "error" in capsys.readouterr().out

    def test_failing_artifact_exits_one(self, tmp_path, capsys):
        assert _mod.main([str(tmp_path / "missing.png")]) == 1
        assert '"ok": false' in capsys.readouterr().out

    def test_no_border_check_disables_the_threshold(self, tmp_path, monkeypatch, capsys):
        seen: list[float | None] = []
        monkeypatch.setattr(
            _mod,
            "verify",
            lambda path, *, kind, min_stddev, save_frames, border_max_stddev: (
                seen.append(border_max_stddev) or {"ok": True}
            ),
        )
        _mod.main([str(tmp_path / "clip.webm"), "--no-border-check"])
        capsys.readouterr()
        assert seen == [None]

    def test_border_threshold_is_configurable(self, tmp_path, monkeypatch, capsys):
        seen: list[float | None] = []
        monkeypatch.setattr(
            _mod,
            "verify",
            lambda path, *, kind, min_stddev, save_frames, border_max_stddev: (
                seen.append(border_max_stddev) or {"ok": True}
            ),
        )
        _mod.main([str(tmp_path / "clip.webm"), "--border-max-stddev", "0.02"])
        capsys.readouterr()
        assert seen == [0.02]
