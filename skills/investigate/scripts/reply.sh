#!/usr/bin/env bash
# Usage: reply.sh <channel_id> <thread_ts> <message>
#
# Posts a threaded reply to a Slack channel using the ExampleCorp bot.

set -euo pipefail

channel_id="${1:?Usage: reply.sh <channel_id> <thread_ts> <message>}"
thread_ts="${2:?Usage: reply.sh <channel_id> <thread_ts> <message>}"
message="${3:?Usage: reply.sh <channel_id> <thread_ts> <message>}"

uvx dev10x skill notify slack-send \
  --channel "$channel_id" \
  --thread-ts "$thread_ts" \
  --message "$message"
