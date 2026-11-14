#!/usr/bin/env bash
# Generate both ~/.claude/.skills-menu.txt and ~/.claude/SKILLS.md
# Pass --force to regenerate even when cache is fresh.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Generate detailed README-style SKILLS.md
"${SCRIPT_DIR}/generate-motd.sh" "$@"

# Generate compact terminal-friendly menu
"${SCRIPT_DIR}/generate-skills-menu.sh" "$@"

echo "✅ Generated both SKILLS.md and .skills-menu.txt"
