#!/usr/bin/env bash
# Sourced by the diagram render scripts (diagram-sequence, diagram-bpmn):
# both hand puppeteer a system browser instead of letting it download one.
# Each caller keeps its own policy for when no browser is found.

find_chrome() {
    local candidate
    for candidate in google-chrome-stable google-chrome chromium chromium-browser; do
        if command -v "$candidate" >/dev/null 2>&1; then
            command -v "$candidate"
            return 0
        fi
    done
    return 1
}
