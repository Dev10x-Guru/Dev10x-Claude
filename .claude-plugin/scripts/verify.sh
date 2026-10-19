#!/usr/bin/env bash
# Post-install verification — checks MCP servers, hooks, and prerequisites.
# Exit 0 if all checks pass, exit 1 if any check fails.

set -euo pipefail

PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$PLUGIN_ROOT/.." && pwd)"

pass=0
fail=0
warn=0

check_pass() { printf '  \033[32m✓\033[0m %s\n' "$1"; pass=$((pass + 1)); }
check_fail() { printf '  \033[31m✗\033[0m %s\n' "$1"; fail=$((fail + 1)); }
check_warn() { printf '  \033[33m!\033[0m %s\n' "$1"; warn=$((warn + 1)); }

echo "=== Dev10x Plugin Verification ==="
echo ""

echo "Prerequisites:"
for cmd in python3 jq git bash; do
    if command -v "$cmd" &>/dev/null; then
        check_pass "$cmd found ($(command -v "$cmd"))"
    else
        check_fail "$cmd not found"
    fi
done

claude_version=$(claude --version 2>/dev/null || echo "")
if [[ -n "$claude_version" ]]; then
    check_pass "Claude CLI: $claude_version"
else
    check_warn "Claude CLI not found (optional for verification)"
fi

echo ""
echo "MCP Servers:"
plugin_json="$PLUGIN_ROOT/plugin.json"
if [[ -f "$plugin_json" ]]; then
    check_pass "plugin.json found"

    for server_name in $(jq -r '.mcpServers // {} | keys[]' "$plugin_json"); do
        server_cmd=$(jq -r ".mcpServers.\"$server_name\".command" "$plugin_json")
        resolved_cmd="${server_cmd//\$\{CLAUDE_PLUGIN_ROOT\}/$REPO_ROOT}"
        if [[ -f "$resolved_cmd" ]]; then
            if [[ -x "$resolved_cmd" ]]; then
                check_pass "MCP server '$server_name': $resolved_cmd (executable)"
            else
                check_fail "MCP server '$server_name': $resolved_cmd (not executable)"
            fi
        else
            check_fail "MCP server '$server_name': $resolved_cmd (missing)"
        fi
    done
else
    check_fail "plugin.json not found at $plugin_json"
fi

echo ""
echo "Hook Scripts:"
hooks_json="$REPO_ROOT/hooks/hooks.json"
if [[ -f "$hooks_json" ]]; then
    check_pass "hooks.json found"

    # Core entries live in hooks.json; each plugin's in hooks/hooks.d (GH-1556).
    hook_files=("$hooks_json")
    for fragment in "$REPO_ROOT"/hooks/hooks.d/*.json; do
        if [[ -f "$fragment" ]]; then
            hook_files+=("$fragment")
        fi
    done

    while IFS= read -r hook_cmd; do
        resolved="${hook_cmd//\$CLAUDE_PLUGIN_ROOT/$REPO_ROOT}"
        script_path=$(echo "$resolved" | awk '{print $NF}')
        hook_base=$(basename "$script_path")

        if [[ -f "$script_path" ]]; then
            if [[ -x "$script_path" ]] || [[ "$resolved" == *"python3"* ]] || [[ "$resolved" == *"bash"* ]]; then
                check_pass "Hook '$hook_base'"
            else
                check_warn "Hook '$hook_base' exists but may not be executable"
            fi
        else
            check_fail "Hook '$hook_base': $script_path (missing)"
        fi
    done < <(jq -r '.. | .command? // empty' "${hook_files[@]}" | sort -u)
else
    check_fail "hooks.json not found"
fi

echo ""
echo "Skills:"
skills_dir="$REPO_ROOT/skills"
if [[ -d "$skills_dir" ]]; then
    skill_count=$(find "$skills_dir" -name "SKILL.md" | wc -l)
    check_pass "$skill_count skills found"

    missing_frontmatter=0
    while IFS= read -r skill_file; do
        if ! head -1 "$skill_file" | grep -q '^---'; then
            missing_frontmatter=$((missing_frontmatter + 1))
        fi
    done < <(find "$skills_dir" -name "SKILL.md")

    if [[ $missing_frontmatter -gt 0 ]]; then
        check_warn "$missing_frontmatter skills missing frontmatter"
    else
        check_pass "All skills have frontmatter"
    fi
else
    check_fail "Skills directory not found"
fi

echo ""
echo "=== Results ==="
printf '  Passed: %d  Failed: %d  Warnings: %d\n' "$pass" "$fail" "$warn"

if [[ $fail -gt 0 ]]; then
    echo ""
    echo "Some checks failed. Review the output above."
    exit 1
fi

echo ""
echo "All checks passed!"
