#!/bin/bash
# Notification 이벤트: Claude Code가 사용자 입력을 기다리는 상태
INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id')
MESSAGE=$(echo "$INPUT" | jq -r '.message // "입력 대기 중"')
CWD=$(echo "$INPUT" | jq -r '.cwd')

mkdir -p "$HOME/.hubest/state"

TMPFILE=$(mktemp "$HOME/.hubest/state/.tmp.XXXXXX")
jq -n \
  --arg sid "$SESSION_ID" \
  --arg msg "$MESSAGE" \
  --arg cwd "$CWD" \
  --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg status "waiting" \
  --arg event "Notification" \
  '{session_id: $sid, message: $msg, cwd: $cwd, timestamp: $ts, status: $status, last_event: $event}' \
  > "$TMPFILE" && mv "$TMPFILE" "$HOME/.hubest/state/${SESSION_ID}.json"

# macOS 네이티브 알림
PROJECT=$(basename "$CWD")
osascript -e "display notification \"$MESSAGE\" with title \"Hubest: $PROJECT\" subtitle \"입력 대기 중\"" 2>/dev/null
