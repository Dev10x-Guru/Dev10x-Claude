#!/usr/bin/env bash
# Release workflow for Dev10x.
#
# Develop uses .dev0 suffixes between releases (e.g. 0.7.0.dev0).
# The release script strips .dev0 to produce the release version,
# tags it, resets main, and bumps develop to the next dev version.
#
# Usage: ./bin/release.sh {features|fixes|major}
#
# Phase 2b prints the remote side effects of a release (PyPI wheel publish,
# marketplace ref move) before the irreversible tag. A human at a TTY
# proceeds automatically; a non-interactive/agent run must set
# CONFIRM_RELEASE=1 to opt in.
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

# Phase 2b: Release notice + agent guard.
# A release is NOT a local action. Pushing the tag triggers a PyPI wheel
# publish (.github/workflows/pypi-publish.yml on v* tags) and the main reset
# moves the marketplace's served ref — both effectively irreversible. This
# notice states those effects plainly. A human at a TTY proceeds; a
# non-interactive/agent run must set CONFIRM_RELEASE=1 so an agent cannot
# trigger a publish by accident.
function release_notice {
    local rc_version="$1"
    local tag="$2"
    local repo_root
    repo_root="$(git rev-parse --show-toplevel)"

    header "Phase 2b · Release effects (read before tagging)"
    echo ""
    echo -e "  Releasing ${BOLD}${tag}${RESET} is not a local action. Tagging will:"
    echo ""
    echo -e "    ${BOLD}•${RESET} push tag ${tag} → CI publishes the wheel to PyPI"
    echo -e "      (https://pypi.org/project/Dev10x/ — a version cannot be reused)"
    echo -e "    ${BOLD}•${RESET} reset main to develop HEAD → the marketplace served ref"
    echo -e "      advances; every 'claude plugin update' jumps to ${rc_version}"
    echo -e "    ${BOLD}•${RESET} create a GitHub release for ${tag}"
    echo ""
    echo -e "  ${YELLOW}These effects are remote and effectively irreversible.${RESET}"
    echo ""
    echo -e "  To smoke-test this candidate first (separate terminal):"
    echo -e "    ${CYAN}${repo_root}/bin/test-local.sh${RESET}   # build + install wheel, verify structure"
    echo -e "    ${CYAN}claude --plugin-dir ${repo_root}${RESET}  # exercise the live plugin runtime"
    echo ""

    if [[ -t 0 ]]; then
        step "Interactive session — proceeding to tag."
        return 0
    fi

    if [[ "${CONFIRM_RELEASE:-}" == "1" ]]; then
        step "CONFIRM_RELEASE=1 — proceeding to tag (non-interactive)."
        return 0
    fi

    echo -e "  ${RED}${BOLD}Non-interactive release blocked.${RESET}" >&2
    echo -e "  ${RED}This run has no TTY (agent or CI). Set CONFIRM_RELEASE=1 to" >&2
    echo -e "  confirm you intend to publish to PyPI and move the marketplace" >&2
    echo -e "  ref, then re-run:${RESET}" >&2
    echo -e "    ${CYAN}CONFIRM_RELEASE=1 $0 {features|fixes|major}${RESET}" >&2
    exit 1
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

    # State the remote side effects before the irreversible tag; block
    # accidental non-interactive releases unless CONFIRM_RELEASE=1.
    release_notice "$rc_version" "$tag"

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
        echo "  CONFIRM_RELEASE=1  Confirm a non-interactive (agent/CI) release"
        exit 1
        ;;
esac
