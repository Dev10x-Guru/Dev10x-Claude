#!/usr/bin/env bash
# Convert QA evidence files for Linear upload.
#
# Usage:
#   convert-evidence.sh screenshots /tmp/Dev10x/self-qa/test1.png /tmp/Dev10x/self-qa/test2.png
#   convert-evidence.sh video /tmp/Dev10x/self-qa/qa-video-dir/recording.webm
#   convert-evidence.sh narrate /tmp/Dev10x/self-qa/qa-video-dir/recording.mp4 vo/track.wav
#   convert-evidence.sh stitch /tmp/Dev10x/playwright/<qa-run> [out.png]
#
# Commands:
#   screenshots  Convert PNGs to JPGs (quality 70, max 1200px wide)
#   video        Convert webm to mp4 (h264, crf 18, yuv420p, faststart)
#   narrate      Mux a voice-over WAV onto an mp4 (audio re-encoded, video copied)
#   stitch       Stack a run directory's PNGs into one evidence sheet
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
        "$(im_tool)" "$src" -quality 70 -resize 1200x "$dst"
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

cmd_narrate() {
    if [[ $# -lt 2 ]]; then
        echo "Usage: convert-evidence.sh narrate <video.mp4> <voiceover.wav> [out.mp4]" >&2
        exit 1
    fi

    local src="$1"
    local vo="$2"
    local dst="${3:-${src%.*}-narrated.mp4}"

    if [[ ! -f "$src" ]]; then
        echo "ERROR: $src not found" >&2
        exit 1
    fi
    if [[ ! -f "$vo" ]]; then
        echo "ERROR: voice-over track $vo not found — run Dev10x:tts first" >&2
        exit 1
    fi

    # No -shortest: the voice-over ends before the recording does whenever
    # the last caption is not the last thing on screen, and -shortest would
    # truncate the video to the audio, silently dropping the closing frames.
    #
    # -c:v copy keeps the already-tuned h264 from cmd_video — re-encoding
    # here would compound the artifacts that CRF 18 was chosen to avoid.
    # 48 kHz AAC because that is what delivery pipelines expect.
    ffmpeg -hide_banner -loglevel error -i "$src" -i "$vo" \
        -map 0:v:0 -map 1:a:0 \
        -c:v copy -c:a aac -b:a 192k -ar 48000 \
        -movflags +faststart "$dst" -y \
        </dev/null

    echo "$dst"
    echo "  Narrated: $(basename "$src") + $(basename "$vo") → $(basename "$dst")" >&2
}

# ImageMagick 7 renamed the entry point to `magick`; 6 shipped `convert`.
# Both spellings exist in the wild and a rule for one does not cover the
# other, so resolve once here rather than leaving the caller to guess.
im_tool() {
    if command -v magick >/dev/null 2>&1; then
        echo "magick"
    elif command -v convert >/dev/null 2>&1; then
        echo "convert"
    else
        echo "ERROR: ImageMagick not found (need 'magick' or 'convert')" >&2
        exit 1
    fi
}

# Stack a QA run's screenshots into a single evidence sheet.
#
# The shape is fixed here rather than assembled ad hoc at the call site:
# an agent that improvises `magick <files> -append` is prompted, and the
# prompt offers `magick *` — a catch-all over an arbitrary output path.
# Constraining the run directory means the output path is bounded by
# construction, so the versioned per-file script rule is sufficient.
cmd_stitch() {
    if [[ $# -eq 0 ]]; then
        echo "Usage: convert-evidence.sh stitch <run-dir> [out.png]" >&2
        exit 1
    fi

    local run_dir="$1"
    local dst="${2:-${run_dir%/}/evidence-sheet.png}"

    if [[ ! -d "$run_dir" ]]; then
        echo "ERROR: $run_dir is not a directory" >&2
        exit 1
    fi

    case "$run_dir" in
        /tmp/Dev10x/*) ;;
        *)
            echo "ERROR: run dir must live under /tmp/Dev10x/ (got: $run_dir)" >&2
            exit 1
            ;;
    esac

    local -a frames=()
    while IFS= read -r frame; do
        frames+=("$frame")
    done < <(find "$run_dir" -maxdepth 1 -name '*.png' ! -name 'evidence-sheet.png' | sort)

    if [[ ${#frames[@]} -eq 0 ]]; then
        echo "ERROR: no PNGs found in $run_dir" >&2
        exit 1
    fi

    # -splice 0x2 between frames draws a hairline separator so stacked
    # screenshots of the same page are told apart at a glance.
    "$(im_tool)" "${frames[@]}" -background '#d0d0d0' -splice 0x2 -append "$dst"

    echo "$dst"
    echo "  Stitched: ${#frames[@]} frames → $(basename "$dst")" >&2
}

case "${1:-}" in
    screenshots) shift; cmd_screenshots "$@" ;;
    video)       shift; cmd_video "$@" ;;
    narrate)     shift; cmd_narrate "$@" ;;
    stitch)      shift; cmd_stitch "$@" ;;
    *)
        echo "Usage: convert-evidence.sh {screenshots|video|narrate|stitch} <files...>" >&2
        exit 1
        ;;
esac
