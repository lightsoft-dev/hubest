#!/bin/bash
# SessionEnd 이벤트: Claude Code 세션 종료
INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id')

if [ -f "$HOME/.hubest/state/${SESSION_ID}.json" ]; then
  rm "$HOME/.hubest/state/${SESSION_ID}.json"
fi
