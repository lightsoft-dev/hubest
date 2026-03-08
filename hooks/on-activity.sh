#!/bin/bash
# PostToolUse 이벤트: Claude Code가 도구를 사용한 직후 — 작업 중 표시
INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id')
CWD=$(echo "$INPUT" | jq -r '.cwd')
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // "unknown"')

mkdir -p "$HOME/.hubest/state"

TMPFILE=$(mktemp "$HOME/.hubest/state/.tmp.XXXXXX")
jq -n \
  --arg sid "$SESSION_ID" \
  --arg msg "Tool: $TOOL_NAME" \
  --arg cwd "$CWD" \
  --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg status "working" \
  --arg event "PostToolUse" \
  '{session_id: $sid, message: $msg, cwd: $cwd, timestamp: $ts, status: $status, last_event: $event}' \
  > "$TMPFILE" && mv "$TMPFILE" "$HOME/.hubest/state/${SESSION_ID}.json"
