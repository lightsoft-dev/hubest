# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Hubest is a multi-project session manager TUI for Claude Code, built on iTerm2 + Claude Code Hooks. It lets you run Claude Code across multiple projects simultaneously and monitor/control all sessions from a single terminal. macOS + iTerm2 only.

## Running

```bash
# Run the TUI (requires: pip3 install textual rich pyyaml)
python3 hubest_cli.py interactive

# Or via the entry point script (expects to be installed at ~/.hubest/bin/hubest)
hubest
```

There are no tests, linter, or build steps.

## Architecture

**Single-file Python app** (`hubest_cli.py`, ~1175 lines) using Textual for TUI and Rich for rendering. The `hubest` bash script is a thin wrapper that delegates to `hubest_cli.py`.

### State Flow

```
Claude Code session → Hook fires → hooks/on-*.sh writes JSON to ~/.hubest/state/{session_id}.json
                                  → TUI polls ~/.hubest/state/ every 1-2 seconds
                                  → Detects changes → updates UI + shows notifications
```

### Key Components in `hubest_cli.py`

- **YAML utils** (lines ~40-100): Load/save `~/.hubest/projects.yaml` with PyYAML fallback to a simple parser
- **State scanning** (`scan_state_dir`): Reads all JSON files from `~/.hubest/state/`
- **iTerm2 integration** (`iterm2_*` functions): AppleScript via `osascript` for tab creation, switching, and text injection
- **Hook injection** (`merge_hooks_into_settings`): Merges hubest hooks into `.claude/settings.json`
- **Natural language routing** (`_route_natural_language`): Matches user input against project keywords to route messages
- **`HubestApp`** (Textual App): Main TUI with `SessionsPanel` (auto-refreshing session table), `OutputLog`, and `CommandInput`
- **Background watcher** (`_background_watcher`): 1-second interval detecting state transitions (working→idle, new waiting states) and showing notifications

### Hook Scripts (`hooks/`)

Each receives JSON on stdin from Claude Code, writes state to `~/.hubest/state/`. All use `jq` for JSON processing and atomic writes via tmpfile+mv.

| Script | Event | Status Written |
|--------|-------|----------------|
| `on-session-start.sh` | SessionStart | idle |
| `on-activity.sh` | PostToolUse | working |
| `on-notification.sh` | Notification | waiting (+ macOS notification) |
| `on-stop.sh` | Stop | idle (preserves last_assistant_message) |
| `on-session-end.sh` | SessionEnd | removes state file |

### Data Files (at runtime, under `~/.hubest/`)

- `projects.yaml` — registered projects with name, path, keywords
- `state/{session_id}.json` — live session state (written by hooks)
- `config.yaml` — stale_hours, watch_interval, version

## Language

All UI text and code comments are in English.
