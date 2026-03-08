#!/bin/bash
# Stop event: Claude Code finished responding, awaiting next prompt
INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id')
CWD=$(echo "$INPUT" | jq -r '.cwd')

# Use the last_assistant_message provided directly by Claude Code
SUMMARY=$(echo "$INPUT" | jq -r '.last_assistant_message // ""' | head -c 500)

# If empty, keep existing message
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
