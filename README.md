# Hubest

A multi-project session manager TUI for Claude Code, built on iTerm2 + Claude Code Hooks.

Run Claude Code across multiple projects simultaneously and monitor/control all sessions from a single terminal.

```
┌──────────────── Hubest ──────────────────────┐
│ Sessions — 3 registered, 2 active            │
│  ● fabric-mall     working  Tool: Write  12s │
│  ● moonlight       waiting  Please review 3m │
│  ○ erp-config      idle                 15m  │
├──────────────────────────────────────────────┤
│ ❯ status                                     │
│ ──── ✅ moonlight — completed ────           │
│ Modified files and refactored logic...       │
│ ─────────────────────────────────            │
│                                              │
│ ⚡ [moonlight] waiting: Allow file deletion? │
├──────────────────────────────────────────────┤
│ Enter a command or message...                │
└──────────────────────────────────────────────┘
```

## Requirements

- **macOS** (iTerm2 only)
- **iTerm2**
- **Python 3.8+**
- **jq** — JSON processing in hook scripts
- **Claude Code** — the tool being managed

## Installation

### Homebrew (recommended)

```bash
brew install lightsoft-dev/tap/hubest
hubest init
```

### Manual

```bash
# 1. Clone
git clone https://github.com/lightsoft-dev/hubest.git
cd hubest

# 2. Install Python dependencies
pip3 install textual rich pyyaml

# 3. Deploy to ~/.hubest
mkdir -p ~/.hubest/{state,iterm,bin}
cp hubest_cli.py ~/.hubest/
cp hubest ~/.hubest/bin/
cp -r hooks/ ~/.hubest/hooks/
chmod +x ~/.hubest/bin/hubest ~/.hubest/hooks/*.sh

# 4. Add to PATH (~/.zshrc or ~/.bashrc)
echo 'export PATH="$HOME/.hubest/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc

# 5. Initialize
hubest init
```

## Registering Projects

```bash
# Injects hubest hooks into each project's .claude/settings.json
hubest add moonlight ~/projects/moonlight-alley
hubest add fabric ~/projects/fabric-shopping-mall
hubest add erp ~/projects/ecount-erp

# Or use global hooks (applies to all projects at once)
hubest add moonlight ~/projects/moonlight-alley --global
```

This automatically injects hubest hooks into the project's `.claude/settings.json`.
With `--global`, hooks are added to `~/.claude/settings.json` so they apply everywhere.

You can edit keywords in `~/.hubest/projects.yaml` after registration:

```yaml
projects:
  - name: moonlight
    path: ~/projects/moonlight-alley
    keywords: ["moonlight", "moon", "alley"]
  - name: fabric
    path: ~/projects/fabric-shopping-mall
    keywords: ["fabric", "mall", "shopping"]
```

## Usage

```bash
hubest          # Launch the TUI
```

### Commands

| Command | Shortcut | Description |
|---------|----------|-------------|
| `status` | `s` | Show all session states |
| `pending` | `p` | List sessions waiting for input, select to switch |
| `switch <project>` | `sw` | Switch to an iTerm2 tab |
| `send <project> <msg>` | | Send a message to a project session |
| `start [project]` | | Create iTerm2 tab + launch Claude Code |
| `stop [project]` | | Clean up session state |
| `dash` | `d` | Refresh session status |
| `projects` | `pr` | List registered projects |
| `add <name> <path>` | | Register a project |
| `help` | `h`, `?` | Show help |
| `exit` | `q` | Quit TUI (Claude Code sessions stay running) |
| `clear` | `cls`, `Ctrl+L` | Clear output |

### Natural Language Routing

Any input that doesn't match a built-in command is treated as a natural language message. It's matched against project keywords and routed to the corresponding Claude Code session.

```
hubest> fix the payment module           → keyword match → routed to fabric
hubest> @moonlight organize chapter 3    → @mention → routed to moonlight
hubest> run database migration           → no match → project selection prompt
```

If the target project's iTerm2 tab doesn't exist, hubest automatically creates it and launches Claude Code.

### Real-time Notifications

When Claude Code is waiting for input or completes a task, hubest shows real-time notifications in the TUI:

- `⚡ [project] waiting: ...` — permission requests, etc.
- `✅ [project] completed` — shows the response content between separator lines

## How It Works

```
Claude Code session → Hook event fires
                    → on-*.sh writes to ~/.hubest/state/{session_id}.json
                    → hubest TUI polls state directory every 1 second
                    → Detects changes → updates session panel + shows notifications
```

5 hook events:

| Hook | Status | Description |
|------|--------|-------------|
| `SessionStart` | idle | Session started |
| `PostToolUse` | working | Tool in use |
| `Notification` | waiting | Waiting for user input |
| `Stop` | idle | Response complete (saves last assistant message) |
| `SessionEnd` | — | Session ended (state file removed) |

## Directory Structure

```
~/.hubest/
├── bin/hubest           # Entry point
├── hubest_cli.py        # Main TUI app
├── hooks/               # Claude Code hook scripts
│   ├── on-notification.sh
│   ├── on-stop.sh
│   ├── on-session-start.sh
│   ├── on-session-end.sh
│   └── on-activity.sh
├── state/               # Session state (written by hooks)
├── projects.yaml        # Registered projects
├── config.yaml          # Configuration
└── history              # Command history
```

## License

MIT
