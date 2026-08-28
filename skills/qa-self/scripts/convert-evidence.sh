#!/usr/bin/env bash
# Convert QA evidence files for Linear upload.
#
# Usage:
#   convert-evidence.sh screenshots /tmp/Dev10x/self-qa/test1.png /tmp/Dev10x/self-qa/test2.png
#   convert-evidence.sh video /tmp/Dev10x/self-qa/qa-video-dir/recording.webm
#
# Commands:
#   screenshots  Convert PNGs to JPGs (quality 70, max 1200px wide)
#   video        Convert webm to mp4 (h264, crf 18, yuv420p, faststart)
#
# Output:
#   Prints converted file paths to stdout, one per line.
#   Originals are NOT deleted.

set -euo pipefail

cmd_screenshots() {
    if [[ $# -eq 0 ]]; then
        echo "Usage: convert-evidence.sh screenshots <file1.png> [file2.png ...]" >&2
        exit 1
    fi

    for src in "$@"; do
        if [[ ! -f "$src" ]]; then
            echo "SKIP: $src not found" >&2
            continue
        fi
        dst="${src%.png}.jpg"
        convert "$src" -quality 70 -resize 1200x "$dst"
        echo "$dst"
        echo "  Converted: $(basename "$src") → $(basename "$dst") ($(du -h "$dst" | cut -f1))" >&2
    done
}

cmd_video() {
    if [[ $# -eq 0 ]]; then
        echo "Usage: convert-evidence.sh video <recording.webm>" >&2
        exit 1
    fi

    local src="$1"
    if [[ ! -f "$src" ]]; then
        echo "ERROR: $src not found" >&2
        exit 1
    fi

    local dst="${src%.webm}.mp4"
    if [[ "$src" == "$dst" ]]; then
        # Source is already mp4 or has no .webm extension
        dst="${src}.mp4"
    fi

    # CRF 18, not 28: CRF is tuned against camera footage, where sensor
    # noise masks compression artifacts. A screen recording is large flat
    # areas plus fine high-contrast glyphs — exactly what CRF punishes,
    # producing mosquito noise around text and smeared thin strokes, baked
    # in before upload so any later re-encode compounds them. For a 1–2
    # minute evidence clip the file-size saving is irrelevant.
    #
    # -pix_fmt yuv420p is explicit: inheriting a non-4:2:0 source format
    # yields an mp4 that some players and web pipelines mishandle.
    ffmpeg -i "$src" -c:v libx264 -preset fast -crf 18 -pix_fmt yuv420p \
        -movflags +faststart "$dst" -y \
        </dev/null

    echo "$dst"
    echo "  Converted: $(basename "$src") → $(basename "$dst") ($(du -h "$dst" | cut -f1))" >&2
}

case "${1:-}" in
    screenshots) shift; cmd_screenshots "$@" ;;
    video)       shift; cmd_video "$@" ;;
    *)
        echo "Usage: convert-evidence.sh {screenshots|video} <files...>" >&2
        exit 1
        ;;
esac
