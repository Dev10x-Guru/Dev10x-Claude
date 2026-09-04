#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Verify captured QA evidence before it is reviewed or uploaded.

A green capture run proves the code ran, not that the artifacts show
anything: a step guarded by a silent conditional no-ops, and the empty
screenshot or content-free video publishes anyway (GH-1086). This script
is the gate between capture and the local review — it fails loud on the
artifact shapes that a passing suite cannot distinguish from success.

Per screenshot:
  - a file-size floor (a blank or truncated PNG is tiny)
  - a non-uniform-frame check (a screenshot of one flat colour shows
    nothing, whatever its dimensions)

Per video:
  - the same size floor
  - frames extracted with ffmpeg at three points through the recording,
    each run through the same uniformity check
  - a border check for the grey padding Playwright leaves when the
    viewport is smaller than ``record_video_size`` (GH-1204)

Uniformity is measured with ImageMagick's ``identify`` (already required
by ``convert-evidence.sh``) as the image's standard deviation, normalised
to 0..1. Frame extraction uses ffmpeg, likewise already required.

Output: a JSON report on stdout. Exit 0 when every artifact passes, 1
when any fails, 2 on a usage or tooling error. Errors are emitted as
JSON on stdout too, so a caller parses exactly one channel (see
`.claude/rules/script-domain-boundaries.md`).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

# A PNG of a single flat colour compresses to a few hundred bytes; a
# real screenshot of an app page does not come close to this floor.
SCREENSHOT_MIN_BYTES = 10_000

# Playwright flushes an empty .webm at a few KB when the context closes
# with nothing recorded.
VIDEO_MIN_BYTES = 50_000

# Normalised standard deviation below which an image carries no visible
# structure. A uniform fill is exactly 0; a login page with one dialog
# on a flat background still measures well above this.
MIN_STDDEV = 0.02

# Fractions of the video duration to sample frames at. Sampling the very
# first and last frames would flag legitimate fade-in/teardown moments.
FRAME_SAMPLE_POINTS = (0.25, 0.5, 0.75)

# Width, in pixels, of the edge strips sampled for the padding check.
BORDER_STRIP_PX = 6

# Playwright's padding is one constant fill, so a strip cut from inside
# it measures a standard deviation of exactly 0. Real page content at
# the frame's edge — even a plain background column — carries gradients,
# borders or antialiasing that clear this threshold comfortably.
BORDER_MAX_STDDEV = 0.005

_SUBPROCESS_TIMEOUT_SECONDS = 60

IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg"})
VIDEO_SUFFIXES = frozenset({".webm", ".mp4"})


class ToolingError(RuntimeError):
    """A required external tool is missing or failed."""


def parse_stddev(raw: str) -> float:
    """Normalise ``identify -format '%[fx:standard_deviation]'`` output.

    ImageMagick emits a 0..1 float for ``fx:`` expressions, but some
    builds print a quantum-scaled integer instead; anything above 1 is
    rescaled against the 16-bit quantum range so the threshold means the
    same thing on both.
    """
    value = float(raw.strip().split()[0])
    if value > 1.0:
        return value / 65535.0
    return value


def frame_timestamps(duration: float) -> list[float]:
    """Sample offsets, in seconds, for a recording of ``duration``."""
    if duration <= 0:
        return []
    return [round(duration * point, 3) for point in FRAME_SAMPLE_POINTS]


def classify(kind: str, path: Path) -> str:
    """Resolve the artifact kind, honouring an explicit override."""
    if kind != "auto":
        return kind
    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return "screenshot"
    if suffix in VIDEO_SUFFIXES:
        return "video"
    raise ToolingError(f"cannot classify {path.name}: unknown extension {suffix!r}")


def _run(argv: list[str]) -> str:
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ToolingError(f"{argv[0]} not found — install it and re-run") from exc
    except subprocess.TimeoutExpired as exc:
        raise ToolingError(f"{argv[0]} timed out after {_SUBPROCESS_TIMEOUT_SECONDS}s") from exc
    if completed.returncode != 0:
        raise ToolingError(f"{argv[0]} failed: {completed.stderr.strip()[:400]}")
    return completed.stdout


def image_stddev(path: Path) -> float:
    return parse_stddev(_run(["identify", "-format", "%[fx:standard_deviation]", str(path)]))


def image_size(path: Path) -> tuple[int, int]:
    raw = _run(["identify", "-format", "%w %h", str(path)]).split()
    try:
        width, height = int(raw[0]), int(raw[1])
    except (IndexError, ValueError) as exc:
        raise ToolingError(f"identify reported no dimensions for {path.name}") from exc
    return width, height


def region_stats(path: Path, *, geometry: str) -> tuple[float, float]:
    """Standard deviation and mean of one cropped region, normalised 0..1.

    ImageMagick crops on read when the geometry is appended to the
    filename, so this costs one process and never writes a temp file.
    """
    raw = _run(
        [
            "identify",
            "-format",
            "%[fx:standard_deviation] %[fx:mean]",
            f"{path}[{geometry}]",
        ]
    ).split()
    if len(raw) < 2:
        raise ToolingError(f"identify reported no statistics for {path.name}[{geometry}]")
    return parse_stddev(raw[0]), parse_stddev(raw[1])


def border_geometries(width: int, height: int, *, strip: int = BORDER_STRIP_PX) -> dict[str, str]:
    """Crop geometries for the right and bottom edge strips of a frame.

    Playwright pads on the right, the bottom, or both — never the top or
    left, because the undersized viewport is anchored top-left.
    """
    geometries: dict[str, str] = {}
    if width > strip:
        geometries["right"] = f"{strip}x{height}+{width - strip}+0"
    if height > strip:
        geometries["bottom"] = f"{width}x{strip}+0+{height - strip}"
    return geometries


def flat_border_edges(path: Path, *, max_stddev: float) -> dict[str, dict]:
    """Edges of ``path`` whose outer strip is a single flat colour.

    A flat edge is the signature of Playwright's padding. The mean rides
    along in the result so the review report can show *which* grey it
    measured — the padding is mid-grey (~0.49), which is also roughly
    what a dimmed modal backdrop reads, so the mean alone never settles
    it and the stddev is what decides.
    """
    width, height = image_size(path)
    flat: dict[str, dict] = {}
    for edge, geometry in border_geometries(width, height).items():
        stddev, mean = region_stats(path, geometry=geometry)
        if stddev < max_stddev:
            flat[edge] = {"stddev": round(stddev, 5), "mean": round(mean, 4)}
    return flat


def video_duration(path: Path) -> float:
    raw = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
    ).strip()
    try:
        return float(raw)
    except ValueError as exc:
        raise ToolingError(f"ffprobe reported no duration for {path.name}") from exc


def extract_frame(path: Path, *, offset: float, dest: Path) -> None:
    _run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            str(offset),
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-y",
            str(dest),
        ]
    )


def size_floor_failures(size: int, min_bytes: int) -> list[str]:
    """The size-floor verdict, shared by both artifact kinds."""
    if size >= min_bytes:
        return []
    return [f"file is {size} bytes, below the {min_bytes}-byte floor"]


def verify_screenshot(path: Path, *, min_bytes: int, min_stddev: float) -> dict:
    size = path.stat().st_size
    stddev = image_stddev(path)
    failures = size_floor_failures(size, min_bytes)
    if stddev < min_stddev:
        failures.append(f"frame is uniform (stddev {stddev:.4f} < {min_stddev})")
    return {
        "path": str(path),
        "kind": "screenshot",
        "ok": not failures,
        "bytes": size,
        "stddev": round(stddev, 4),
        "failures": failures,
    }


def padded_edge_failures(frames: list[dict]) -> list[str]:
    """The padding verdict: an edge flat in *every* sampled frame.

    Content moves between the three sample points; Playwright's padding
    does not. Requiring the edge to be flat in all of them keeps a
    single frame that happens to end on a plain background from failing
    an otherwise good take.
    """
    borders = [frame.get("flat_edges") for frame in frames]
    if not borders or any(edge_map is None for edge_map in borders):
        return []
    persistent = set.intersection(*(set(edge_map) for edge_map in borders))
    if not persistent:
        return []
    edges = ", ".join(sorted(persistent))
    return [
        f"{edges} edge is a flat fill in every sampled frame — the capture is "
        "padded, so the viewport was smaller than record_video_size (GH-1204)"
    ]


def verify_video(
    path: Path,
    *,
    min_bytes: int,
    min_stddev: float,
    save_frames: Path | None = None,
    border_max_stddev: float | None = BORDER_MAX_STDDEV,
) -> dict:
    size = path.stat().st_size
    failures = size_floor_failures(size, min_bytes)

    duration = video_duration(path)
    frames: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="dx-evidence-") as tmp:
        # The sampled frames are what a human actually looks at during the
        # pre-upload review, so keep them when a destination is given —
        # a discarded frame plus a stddev number is not something anyone
        # can review.
        frame_dir = save_frames or Path(tmp)
        frame_dir.mkdir(parents=True, exist_ok=True)
        for index, offset in enumerate(frame_timestamps(duration)):
            dest = frame_dir / f"{path.stem}-frame-{index}.png"
            extract_frame(path, offset=offset, dest=dest)
            stddev = image_stddev(dest)
            frame = {"at": offset, "stddev": round(stddev, 4)}
            if border_max_stddev is not None:
                frame["flat_edges"] = flat_border_edges(dest, max_stddev=border_max_stddev)
            if save_frames:
                frame["path"] = str(dest)
            frames.append(frame)

    if not frames:
        failures.append("recording has no duration — the context was never flushed")
    elif all(frame["stddev"] < min_stddev for frame in frames):
        failures.append(
            f"every sampled frame is uniform (max stddev "
            f"{max(frame['stddev'] for frame in frames):.4f} < {min_stddev})"
        )
    else:
        failures.extend(padded_edge_failures(frames))

    return {
        "path": str(path),
        "kind": "video",
        "ok": not failures,
        "bytes": size,
        "duration": round(duration, 2),
        "frames": frames,
        "failures": failures,
    }


def verify(
    path: Path,
    *,
    kind: str,
    min_stddev: float,
    save_frames: Path | None = None,
    border_max_stddev: float | None = BORDER_MAX_STDDEV,
) -> dict:
    if not path.is_file():
        return {
            "path": str(path),
            "kind": kind,
            "ok": False,
            "failures": ["file does not exist"],
        }
    resolved = classify(kind, path)
    if resolved == "screenshot":
        return verify_screenshot(path, min_bytes=SCREENSHOT_MIN_BYTES, min_stddev=min_stddev)
    return verify_video(
        path,
        min_bytes=VIDEO_MIN_BYTES,
        min_stddev=min_stddev,
        save_frames=save_frames,
        border_max_stddev=border_max_stddev,
    )


def build_report(artifacts: list[dict]) -> dict:
    failed = [artifact for artifact in artifacts if not artifact["ok"]]
    return {
        "ok": not failed,
        "checked": len(artifacts),
        "failed": len(failed),
        "artifacts": artifacts,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify QA evidence artifacts.")
    parser.add_argument("files", nargs="+", help="screenshot and/or video paths")
    parser.add_argument(
        "--kind",
        choices=["auto", "screenshot", "video"],
        default="auto",
        help="artifact kind (default: inferred from the extension)",
    )
    parser.add_argument(
        "--min-stddev",
        type=float,
        default=MIN_STDDEV,
        help=f"uniformity threshold, normalised 0..1 (default: {MIN_STDDEV})",
    )
    parser.add_argument(
        "--save-frames",
        type=Path,
        default=None,
        metavar="DIR",
        help=(
            "keep the frames sampled from each video in DIR (and report their"
            " paths) so a human can review the footage without playing it"
        ),
    )
    parser.add_argument(
        "--border-max-stddev",
        type=float,
        default=BORDER_MAX_STDDEV,
        help=(
            "flatness threshold for the padding check, normalised 0..1"
            f" (default: {BORDER_MAX_STDDEV})"
        ),
    )
    parser.add_argument(
        "--no-border-check",
        action="store_true",
        help=(
            "skip the padding check — for a page whose right or bottom edge"
            " genuinely is a single flat colour"
        ),
    )
    args = parser.parse_args(argv)

    try:
        artifacts = [
            verify(
                Path(name),
                kind=args.kind,
                min_stddev=args.min_stddev,
                save_frames=args.save_frames,
                border_max_stddev=None if args.no_border_check else args.border_max_stddev,
            )
            for name in args.files
        ]
    except ToolingError as exc:
        print(json.dumps({"error": str(exc)}))
        return 2

    report = build_report(artifacts)
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
