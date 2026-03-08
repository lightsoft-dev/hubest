#!/bin/bash
# SessionStart 이벤트: 새 Claude Code 세션 시작
INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id')
CWD=$(echo "$INPUT" | jq -r '.cwd')

mkdir -p "$HOME/.hubest/state"

TMPFILE=$(mktemp "$HOME/.hubest/state/.tmp.XXXXXX")
jq -n \
  --arg sid "$SESSION_ID" \
  --arg cwd "$CWD" \
  --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg status "idle" \
  --arg event "SessionStart" \
  '{session_id: $sid, message: "세션 시작됨", cwd: $cwd, timestamp: $ts, status: $status, last_event: $event}' \
  > "$TMPFILE" && mv "$TMPFILE" "$HOME/.hubest/state/${SESSION_ID}.json"
