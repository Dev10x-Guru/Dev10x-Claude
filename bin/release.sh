#!/usr/bin/env bash
# Release workflow for Dev10x.
#
# Develop uses .dev0 suffixes between releases (e.g. 0.7.0.dev0).
# The release script strips .dev0 to produce the release version,
# tags it, resets main, and bumps develop to the next dev version.
#
# Usage: ./bin/release.sh {features|fixes|major}
#
# A dogfood smoke gate (Phase 2b) blocks tagging until you confirm
# that you have run a real --plugin-dir session with the release candidate.
# Skip with SKIP_DOGFOOD=1 (CI-only escape hatch — never for human releases).
set -euo pipefail

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
BOLD='\033[1m'
RESET='\033[0m'

VERSION_FILES=".bumpversion.toml .claude-plugin/plugin.json pyproject.toml uv.lock skills/playbook/references/playbook.yaml"

command -v bump-my-version >/dev/null || {
    echo "bump-my-version not found. Install: pip install bump-my-version" >&2
    exit 1
}
command -v gh >/dev/null || {
    echo "gh not found. Install: https://cli.github.com" >&2
    exit 1
}

function current_version {
    bump-my-version show current_version
}

function header {
    echo ""
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
    echo -e "${CYAN}  $1${RESET}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
}

function step {
    echo -e "  ${GREEN}▸${RESET} $1"
}

function sync_branches {
    header "Phase 1 · Synchronize branches"
    step "Checking out develop..."
    git checkout develop
    git pull origin develop
    step "Checking out main..."
    git checkout main
    git pull origin main
    step "Rebasing develop on main..."
    git checkout develop
    git rebase main
}

function finalize_version {
    local current
    current=$(current_version)
    local release="${current%.dev*}"
    if [[ "$current" == "$release" ]]; then
        echo "⚠️  Version $current has no dev suffix — nothing to finalize" >&2
        exit 1
    fi
    step "Finalizing: ${current} → ${release}"
    bump-my-version bump --new-version "$release" --no-tag --no-commit
    git add $VERSION_FILES
    git commit -m "🔖 Bump version: ${current} → ${release}"
}

function bump_version {
    local version_type=$1
    local before
    before=$(current_version)
    bump-my-version bump "$version_type" --no-tag --no-commit
    local after
    after=$(current_version)
    step "Bumping: ${before} → ${after}"
    git add $VERSION_FILES
    git commit -m "🔖 Bump version: ${before} → ${after}"
}

# Detect the installed marketplace plugin version, if any.
# Prints the version string or "unknown" if not detectable.
function installed_plugin_version {
    local plugin_json=""
    # Try ~/.claude/plugins/Dev10x-Claude/plugin.json (marketplace install path)
    if [[ -f "${HOME}/.claude/plugins/Dev10x-Claude/plugin.json" ]]; then
        plugin_json="${HOME}/.claude/plugins/Dev10x-Claude/plugin.json"
    elif [[ -f "${HOME}/.config/claude/plugins/Dev10x-Claude/plugin.json" ]]; then
        plugin_json="${HOME}/.config/claude/plugins/Dev10x-Claude/plugin.json"
    fi
    if [[ -n "$plugin_json" ]]; then
        # Extract version field with jq if available, otherwise grep
        if command -v jq >/dev/null 2>&1; then
            jq -r '.version // "unknown"' "$plugin_json" 2>/dev/null || echo "unknown"
        else
            grep -o '"version"[[:space:]]*:[[:space:]]*"[^"]*"' "$plugin_json" \
                | grep -o '"[^"]*"$' | tr -d '"' 2>/dev/null || echo "unknown"
        fi
    else
        echo "unknown"
    fi
}

# Phase 2b: Dogfood smoke gate.
# Require the releaser to confirm a real --plugin-dir session before tagging.
# This gate exists because CI only runs under mocks; the only true runtime
# validation of MCP-server and permission-hook changes requires a live session
# with the develop checkout loaded via --plugin-dir.
function dogfood_gate {
    local rc_version="$1"
    local repo_root
    repo_root="$(git rev-parse --show-toplevel)"

    if [[ "${SKIP_DOGFOOD:-}" == "1" ]]; then
        echo -e "  ${YELLOW}⚠  SKIP_DOGFOOD=1 — skipping dogfood gate (CI mode)${RESET}"
        return 0
    fi

    header "Phase 2b · Dogfood smoke gate (REQUIRED before tagging)"

    # Surface version-skew information so the releaser knows what they're testing.
    local installed
    installed="$(installed_plugin_version)"
    echo ""
    echo -e "  ${BOLD}Release candidate:${RESET} ${rc_version}"
    if [[ "$installed" == "unknown" ]]; then
        echo -e "  ${BOLD}Installed plugin:${RESET}  not detected (marketplace checkout absent)"
    elif [[ "$installed" == "$rc_version" ]]; then
        echo -e "  ${BOLD}Installed plugin:${RESET}  ${installed} ${GREEN}(matches RC — no skew)${RESET}"
    else
        echo -e "  ${BOLD}Installed plugin:${RESET}  ${installed} ${YELLOW}⚠ version skew — installed lags RC${RESET}"
        echo -e "  ${YELLOW}  The in-session MCP server will be the OLD plugin until you restart${RESET}"
        echo -e "  ${YELLOW}  claude with --plugin-dir pointing to this checkout.${RESET}"
    fi

    echo ""
    echo -e "  ${BOLD}Before confirming, you must run a real --plugin-dir session:${RESET}"
    echo ""
    echo -e "    ${CYAN}claude --plugin-dir ${repo_root}${RESET}"
    echo ""
    echo -e "  ${BOLD}Minimum smoke checklist:${RESET}"
    echo "    □  Start a session and verify the plugin loads without errors"
    echo "    □  Run one Dev10x skill that exercises recent MCP-server changes"
    echo "       e.g. Dev10x:gh-pr-review or Dev10x:gh-pr-respond"
    echo "       (hits resolve_review_thread + pr_get — both new in this cycle)"
    echo "    □  Run one git commit via Dev10x:git-commit"
    echo "       (exercises bash tokenizer + privilege-escalation denies)"
    echo "    □  Confirm no unexpected permission prompts or tool errors"
    echo ""
    echo -e "  ${BOLD}Optionally document the smoke run in docs/smoke-runs/:${RESET}"
    echo "    echo \"\$(date -u +%Y-%m-%dT%H:%M:%SZ)  ${rc_version}  OK\" >> docs/smoke-runs/log.txt"
    echo ""
    echo -e "  ${RED}${BOLD}This gate blocks an irreversible tag. CI alone is not enough.${RESET}"
    echo ""
    echo -e "  Type ${BOLD}ship ${rc_version}${RESET} to confirm you have completed the smoke run:"
    read -r confirmation

    local expected="ship ${rc_version}"
    if [[ "$confirmation" != "$expected" ]]; then
        echo ""
        echo -e "  ${RED}✗ Confirmation mismatch. Expected: '${expected}'${RESET}"
        echo -e "  ${RED}  Tagging aborted. Complete the smoke run and re-run release.sh.${RESET}"
        echo ""
        exit 1
    fi

    echo ""
    echo -e "  ${GREEN}✓ Dogfood smoke confirmed. Proceeding to tag.${RESET}"
}

function release {
    local pre_bump="${1:-}"

    header "Phase 2 · Prepare release version"
    if [[ -n "$pre_bump" ]]; then
        bump_version "$pre_bump"
    fi
    finalize_version

    local tag="v$(current_version)"
    local rc_version
    rc_version="$(current_version)"

    # Dogfood gate: must pass before the tag is created.
    dogfood_gate "$rc_version"

    header "Phase 3 · Tag and push"
    step "Creating tag: $tag"
    git tag -f "$tag" -m "Release $tag"
    git push origin "$tag"

    step "Resetting main to develop HEAD..."
    git checkout main
    git reset --hard develop
    git checkout develop

    header "Phase 4 · Advance develop to next dev version"
    bump_version "minor"
    step "Pushing develop and main..."
    git push origin develop
    git push origin main

    header "Phase 5 · Create GitHub release"
    git checkout main
    step "Creating release for $tag..."
    gh release create "$tag" --generate-notes
    git checkout develop

    echo ""
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
    echo -e "${GREEN}  ✅ Released $tag${RESET}"
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
}

case "${1:-}" in
    major)
        echo -e "${YELLOW}🎉 Releasing new major version...${RESET}"
        sync_branches
        release "major"
        ;;
    features)
        echo -e "${YELLOW}🎉 Releasing new minor version (features)...${RESET}"
        sync_branches
        release
        ;;
    fixes)
        echo -e "${YELLOW}🎉 Releasing new patch version (fixes)...${RESET}"
        sync_branches
        release "patch"
        ;;
    *)
        echo "Usage: $0 {major|features|fixes}"
        echo ""
        echo "  features  Strip .dev0, tag, release, bump to next minor .dev0"
        echo "  fixes     Bump patch, strip .dev0, tag, release, bump to next minor .dev0"
        echo "  major     Bump major, strip .dev0, tag, release, bump to next minor .dev0"
        echo ""
        echo "Environment:"
        echo "  SKIP_DOGFOOD=1  Skip the dogfood smoke gate (CI only)"
        exit 1
        ;;
esac
