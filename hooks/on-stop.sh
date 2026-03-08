#!/bin/bash
# Stop 이벤트: Claude Code가 응답 완료, 다음 프롬프트 대기
INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id')
CWD=$(echo "$INPUT" | jq -r '.cwd')

# Claude Code가 직접 제공하는 last_assistant_message 사용
SUMMARY=$(echo "$INPUT" | jq -r '.last_assistant_message // ""' | head -c 500)

# 없으면 기존 메시지 유지
if [ -z "$SUMMARY" ]; then
  if [ -f "$HOME/.hubest/state/${SESSION_ID}.json" ]; then
    SUMMARY=$(jq -r '.message // ""' "$HOME/.hubest/state/${SESSION_ID}.json")
  fi
fi

mkdir -p "$HOME/.hubest/state"

TMPFILE=$(mktemp "$HOME/.hubest/state/.tmp.XXXXXX")
jq -n \
  --arg sid "$SESSION_ID" \
  --arg msg "$SUMMARY" \
  --arg cwd "$CWD" \
  --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg status "idle" \
  --arg event "Stop" \
  '{session_id: $sid, message: $msg, cwd: $cwd, timestamp: $ts, status: $status, last_event: $event}' \
  > "$TMPFILE" && mv "$TMPFILE" "$HOME/.hubest/state/${SESSION_ID}.json"
