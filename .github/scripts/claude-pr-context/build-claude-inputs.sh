#!/usr/bin/env bash
# Build a Claude CI step's `prompt` and `claude_args` from the files under
# .github/claude/ (GH-1625), so the workflow, gh-review-setup and a local
# review mode all read the same text.
#
# Runs from the trusted base ref (staged into RUNNER_TEMP like
# gather-pr-context.sh). The workflow copies .github/claude/ from that
# ref over the checkout first, so a PR cannot rewrite its own prompt.
#
# Usage: build-claude-inputs.sh <args-file> <prompt-part>...
#   Paths are relative to CLAUDE_CI_DIR (default .github/claude).
#   Parts are joined with one blank line; the static text stays first so
#   the API serves it from the prompt cache, and the RUN_CONTEXT env value
#   (the per-run values) is appended last under a `RUN CONTEXT:` header.
# Outputs: `prompt` and `claude_args` in GITHUB_OUTPUT, or stdout when
#   GITHUB_OUTPUT is unset.
set -euo pipefail

CLAUDE_CI_DIR="${CLAUDE_CI_DIR:-.github/claude}"
: "${RUN_CONTEXT:?set RUN_CONTEXT to the per-run values}"

if (($# < 2)); then
  echo "usage: $0 <args-file> <prompt-part>..." >&2
  exit 2
fi

refuse_expressions() {
  if grep -qF '${{' "$1"; then
    echo "::error::$1 contains \${{ }}: per-run values belong in RUN_CONTEXT" >&2
    exit 1
  fi
}

args_file="$CLAUDE_CI_DIR/$1"
shift

# grep -c '' also counts a final line with no newline, which wc -l misses.
if [[ ! -r "$args_file" || $(grep -c '' "$args_file") -ne 1 ]]; then
  echo "::error::$args_file must hold exactly one line of claude_args" >&2
  exit 1
fi
refuse_expressions "$args_file"
claude_args=$(< "$args_file")

prompt=""
for part in "$@"; do
  path="$CLAUDE_CI_DIR/$part"
  if [[ ! -r "$path" ]]; then
    echo "::error::prompt part $path is missing" >&2
    exit 1
  fi
  refuse_expressions "$path"
  prompt+="$(< "$path")"$'\n\n'
done
prompt+=$'RUN CONTEXT:\n'"$RUN_CONTEXT"

out="${GITHUB_OUTPUT:-/dev/stdout}"
delimiter="EOF_$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')"
{
  printf 'claude_args=%s\n' "$claude_args"
  echo "prompt<<$delimiter"
  printf '%s\n' "$prompt"
  echo "$delimiter"
} >> "$out"
