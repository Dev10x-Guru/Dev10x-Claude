#!/usr/bin/env bash
# GIT_SEQUENCE_EDITOR replacement — reads rebase instructions from
# a caller-provided path via GROOM_SEQ_FILE env var.
#
# Usage:
#   GROOM_SEQ_FILE=/tmp/Dev10x/git/rebase-seq.abc123.txt \
#   GIT_SEQUENCE_EDITOR=.../git-seq-editor.sh git rebase -i ...

set -euo pipefail

TODO_FILE="${1:?GIT_SEQUENCE_EDITOR was called without a todo file argument}"
SEQ_SOURCE="${GROOM_SEQ_FILE:?GROOM_SEQ_FILE env var must point to the rebase-seq file}"

if [[ ! -f "$SEQ_SOURCE" ]]; then
    echo "ERROR: $SEQ_SOURCE not found." >&2
    echo "Write the rebase todo to that file before running git rebase." >&2
    exit 1
fi

cp "$SEQ_SOURCE" "$TODO_FILE"
