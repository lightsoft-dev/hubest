#!/bin/bash
# SessionEnd event: Claude Code session has ended
INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id')

if [ -f "$HOME/.hubest/state/${SESSION_ID}.json" ]; then
  rm "$HOME/.hubest/state/${SESSION_ID}.json"
fi
