#!/usr/bin/env python3
"""Hubest — Claude Code Multi-Session Manager TUI"""

import sys
import os
import json
import re
import subprocess
import shutil
from datetime import datetime, timezone
from pathlib import Path

HUBEST_DIR = Path.home() / '.hubest'
STATE_DIR = HUBEST_DIR / 'state'
PROJECTS_FILE = HUBEST_DIR / 'projects.yaml'
HISTORY_FILE = HUBEST_DIR / 'history'
CONFIG_FILE = HUBEST_DIR / 'config.yaml'

VERSION = '0.1.0'
STALE_HOURS = 24

COMMAND_ALIASES = {
    's': 'status', 'p': 'pending', 'sw': 'switch',
    'd': 'dash', 'pr': 'projects', 'h': 'help',
    '?': 'help', 'q': 'exit', 'quit': 'exit', 'cls': 'clear',
}

HOOKS_CONFIG = {
    "hooks": {
        "Notification": [{"matcher": "", "hooks": [{"type": "command", "command": str(HUBEST_DIR / "hooks" / "on-notification.sh"), "async": True, "timeout": 10}]}],
        "Stop": [{"matcher": "", "hooks": [{"type": "command", "command": str(HUBEST_DIR / "hooks" / "on-stop.sh"), "async": True, "timeout": 10}]}],
        "SessionStart": [{"matcher": "", "hooks": [{"type": "command", "command": str(HUBEST_DIR / "hooks" / "on-session-start.sh"), "async": True, "timeout": 10}]}],
        "SessionEnd": [{"matcher": "", "hooks": [{"type": "command", "command": str(HUBEST_DIR / "hooks" / "on-session-end.sh"), "async": True, "timeout": 10}]}],
        "PostToolUse": [{"matcher": "", "hooks": [{"type": "command", "command": str(HUBEST_DIR / "hooks" / "on-activity.sh"), "async": True, "timeout": 10}]}],
    }
}

# --- YAML Utils ---

def _load_yaml(path):
    try:
        import yaml
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        return _simple_yaml_load(path)

def _save_yaml(path, data):
    try:
        import yaml
        with open(path, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    except ImportError:
        _simple_yaml_save(path, data)

def _simple_yaml_load(path):
    if not os.path.exists(path):
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    data = {'projects': []}
    current_project = None
    for line in content.split('\n'):
        stripped = line.strip()
        if stripped.startswith('- name:'):
            current_project = {'name': stripped.split(':', 1)[1].strip().strip('"').strip("'")}
            data['projects'].append(current_project)
        elif stripped.startswith('path:') and current_project is not None:
            current_project['path'] = stripped.split(':', 1)[1].strip().strip('"').strip("'")
        elif stripped.startswith('keywords:') and current_project is not None:
            kw_str = stripped.split(':', 1)[1].strip()
            if kw_str.startswith('['):
                kw_str = kw_str.strip('[]')
                current_project['keywords'] = [k.strip().strip('"').strip("'") for k in kw_str.split(',') if k.strip()]
            else:
                current_project['keywords'] = []
        elif stripped.startswith('- ') and current_project is not None and 'keywords' in current_project:
            kw = stripped[2:].strip().strip('"').strip("'")
            if kw and not kw.startswith('name:'):
                current_project['keywords'].append(kw)
    return data

def _simple_yaml_save(path, data):
    lines = ['projects:']
    for p in data.get('projects', []):
        lines.append(f'  - name: {p["name"]}')
        lines.append(f'    path: {p["path"]}')
        kws = ', '.join(f'"{k}"' for k in p.get('keywords', []))
        lines.append(f'    keywords: [{kws}]')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')

# --- Utility Functions ---

def load_projects():
    if not PROJECTS_FILE.exists():
        return []
    data = _load_yaml(str(PROJECTS_FILE))
    return data.get('projects', [])

def save_projects(projects):
    _save_yaml(str(PROJECTS_FILE), {'projects': projects})

def scan_state_dir():
    states = {}
    if not STATE_DIR.exists():
        return states
    for f in STATE_DIR.iterdir():
        if f.suffix == '.json' and not f.name.startswith('.'):
            try:
                with open(f, 'r', encoding='utf-8') as fh:
                    data = json.load(fh)
                sid = data.get('session_id', f.stem)
                states[sid] = data
            except (json.JSONDecodeError, OSError):
                pass
    return states

def time_ago(timestamp_str):
    try:
        ts = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        diff = now - ts
        seconds = int(diff.total_seconds())
        if seconds < 0:
            return 'just now'
        if seconds < 60:
            return f'{seconds}s ago'
        minutes = seconds // 60
        if minutes < 60:
            return f'{minutes}m ago'
        hours = minutes // 60
        if hours < 24:
            return f'{hours}h ago'
        days = hours // 24
        return f'{days}d ago'
    except (ValueError, TypeError):
        return 'unknown'

def is_stale(timestamp_str):
    try:
        ts = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        diff = now - ts
        return diff.total_seconds() > STALE_HOURS * 3600
    except (ValueError, TypeError):
        return True

def project_name_from_cwd(cwd, projects):
    cwd_resolved = str(Path(cwd).expanduser().resolve())
    for p in projects:
        p_path = str(Path(p['path']).expanduser().resolve())
        if cwd_resolved == p_path or cwd_resolved.startswith(p_path + '/'):
            return p['name']
    return os.path.basename(cwd)

def merge_hooks_into_settings(settings_path):
    settings_path = Path(settings_path)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    if settings_path.exists():
        with open(settings_path, 'r', encoding='utf-8') as f:
            try:
                settings = json.load(f)
            except json.JSONDecodeError:
                settings = {}
    else:
        settings = {}
    if 'hooks' not in settings:
        settings['hooks'] = {}
    for event_name, event_entries in HOOKS_CONFIG['hooks'].items():
        if event_name not in settings['hooks']:
            settings['hooks'][event_name] = []
        existing = settings['hooks'][event_name]
        for new_entry in event_entries:
            new_cmd = new_entry['hooks'][0]['command']
            already_exists = any(
                h.get('command') == new_cmd
                for ee in existing for h in ee.get('hooks', [])
            )
            if not already_exists:
                existing.append(new_entry)
    with open(settings_path, 'w', encoding='utf-8') as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)

def _find_iterm_session(project_name):
    """Find an iTerm2 session containing hubest:{project_name} and return whether it exists."""
    target_title = f'hubest:{project_name}'
    script = f'''
    tell application "iTerm2"
        repeat with w in windows
            repeat with t in tabs of w
                tell current session of t
                    if name contains "{target_title}" then
                        return "found"
                    end if
                end tell
            end repeat
        end repeat
        return "not_found"
    end tell
    '''
    try:
        result = subprocess.run(['osascript', '-e', script], capture_output=True, timeout=5, text=True)
        return result.stdout.strip() == 'found'
    except (subprocess.SubprocessError, FileNotFoundError):
        return False

def iterm2_switch_tab(project_name):
    target_title = f'hubest:{project_name}'
    script = f'''
    tell application "iTerm2"
        activate
        repeat with w in windows
            repeat with t in tabs of w
                tell current session of t
                    if name contains "{target_title}" then
                        select t
                        return "found"
                    end if
                end tell
            end repeat
        end repeat
        return "not_found"
    end tell
    '''
    try:
        result = subprocess.run(['osascript', '-e', script], capture_output=True, timeout=5, text=True)
        return result.stdout.strip() == 'found'
    except (subprocess.SubprocessError, FileNotFoundError):
        return False

def iterm2_send_text(project_name, text):
    """Send text to existing hubest:{project_name} session without switching tabs."""
    target_title = f'hubest:{project_name}'
    escaped_text = text.replace('\\', '\\\\').replace('"', '\\"')
    script = f'''
    tell application "iTerm2"
        repeat with w in windows
            repeat with t in tabs of w
                tell current session of t
                    if name contains "{target_title}" then
                        write text "{escaped_text}"
                        return "found"
                    end if
                end tell
            end repeat
        end repeat
        return "not_found"
    end tell
    '''
    try:
        result = subprocess.run(['osascript', '-e', script], capture_output=True, timeout=5, text=True)
        return result.stdout.strip() == 'found'
    except (subprocess.SubprocessError, FileNotFoundError):
        return False

def iterm2_create_tab(project_name, project_path):
    """Create a new tab and run Claude Code. Focus returns to original tab."""
    expanded_path = str(Path(project_path).expanduser().resolve())
    script = f'''
    tell application "iTerm2"
        tell current window
            set originalTab to current tab
            set newTab to (create tab with default profile)
            tell current session of newTab
                set name to "hubest:{project_name}"
                write text "cd {expanded_path} && claude"
            end tell
            select originalTab
        end tell
    end tell
    '''
    try:
        subprocess.run(['osascript', '-e', script], capture_output=True, timeout=10)
        return True
    except (subprocess.SubprocessError, FileNotFoundError):
        return False

def find_project_by_name(name, projects):
    name_lower = name.lower()
    for p in projects:
        if p['name'].lower() == name_lower:
            return p
        for kw in p.get('keywords', []):
            if kw.lower() == name_lower:
                return p
    for p in projects:
        if name_lower in p['name'].lower():
            return p
    return None

# --- One-shot Commands ---

def cmd_init():
    print()
    print('  Hubest Initial Setup')
    print('  ' + '─' * 40)
    print()
    dirs = [HUBEST_DIR, STATE_DIR, HUBEST_DIR / 'hooks', HUBEST_DIR / 'iterm', HUBEST_DIR / 'bin']
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
        print(f'  ✅ {d}')
    if not PROJECTS_FILE.exists():
        _save_yaml(str(PROJECTS_FILE), {'projects': []})
        print(f'  ✅ {PROJECTS_FILE} (template created)')
    else:
        print(f'  ⏭  {PROJECTS_FILE} (already exists)')
    if not CONFIG_FILE.exists():
        _save_yaml(str(CONFIG_FILE), {'stale_hours': 24, 'watch_interval': 1, 'version': VERSION})
        print(f'  ✅ {CONFIG_FILE}')
    else:
        print(f'  ⏭  {CONFIG_FILE} (already exists)')
    hooks_dir = HUBEST_DIR / 'hooks'
    for hf in ['on-notification.sh', 'on-stop.sh', 'on-session-start.sh', 'on-session-end.sh', 'on-activity.sh']:
        hp = hooks_dir / hf
        if hp.exists():
            os.chmod(hp, 0o755)
            print(f'  ✅ {hp} (chmod +x)')
        else:
            print(f'  ⚠️  {hp} missing — please reinstall hubest')
    hubest_bin = HUBEST_DIR / 'bin' / 'hubest'
    if hubest_bin.exists():
        os.chmod(hubest_bin, 0o755)
        print(f'  ✅ {hubest_bin} (chmod +x)')
    print()
    print('  Dependency Check')
    print('  ' + '─' * 40)
    deps_ok = True
    if shutil.which('jq'):
        print('  ✅ jq')
    else:
        print('  ❌ jq — brew install jq')
        deps_ok = False
    if shutil.which('python3'):
        print('  ✅ python3')
    else:
        print('  ❌ python3')
        deps_ok = False
    try:
        import textual
        print(f'  ✅ textual ({textual.__version__})')
    except ImportError:
        print('  ❌ textual — pip3 install textual')
        deps_ok = False
    try:
        import yaml
        print(f'  ✅ pyyaml ({yaml.__version__})')
    except ImportError:
        print('  ⚠️  pyyaml not found (optional) — pip3 install pyyaml')
    print()
    if deps_ok:
        print('  ✅ Initial setup complete!')
    else:
        print('  ⚠️  Please install missing dependencies and run again.')
    hubest_bin_dir = str(HUBEST_DIR / 'bin')
    if hubest_bin_dir not in os.environ.get('PATH', '').split(':'):
        print()
        print(f'  💡 Add to your PATH:')
        print(f'     export PATH="$HOME/.hubest/bin:$PATH"')
    print()
    print('  Next step: Register a project with hubest add <name> <path>')
    print()

def cmd_add_oneshot(args):
    parts = args.split()
    if len(parts) < 2:
        print('  Usage: hubest add <name> <path> [--global]')
        return
    use_global = '--global' in parts
    parts = [p for p in parts if p != '--global']
    _do_add_project(parts[0], parts[1], use_global)

def _do_add_project(name, path, use_global=False):
    expanded_path = str(Path(path).expanduser().resolve())
    if not os.path.isdir(expanded_path):
        print(f'  ❌ Directory does not exist: {expanded_path}')
        return
    projects = load_projects()
    for p in projects:
        if p['name'] == name:
            print(f'  ⚠️  Project "{name}" is already registered.')
            return
    keywords = [name]
    if '-' in name:
        keywords.extend(name.split('-'))
    dirname = os.path.basename(expanded_path)
    if dirname != name and dirname not in keywords:
        keywords.append(dirname)
    project = {'name': name, 'path': path, 'keywords': keywords}
    projects.append(project)
    save_projects(projects)
    print(f'  ✅ Project registered: {name} → {path}')
    print(f'     Keywords: {keywords}')
    if use_global:
        settings_path = Path.home() / '.claude' / 'settings.json'
        merge_hooks_into_settings(settings_path)
        print(f'  ✅ Global hooks injected: {settings_path}')
    else:
        settings_path = Path(expanded_path) / '.claude' / 'settings.json'
        merge_hooks_into_settings(settings_path)
        print(f'  ✅ Project hooks injected: {settings_path}')


# --- Textual TUI ---

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Header, Footer, Static, Input, RichLog
from textual.reactive import reactive
from textual import work
from rich.text import Text
from rich.table import Table
from rich.panel import Panel
from rich.console import Group


class SessionsPanel(Static):
    """Widget that displays session status in real-time."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.projects = load_projects()

    def on_mount(self):
        self.set_interval(2, self.refresh_display)
        self.refresh_display()

    def refresh_display(self):
        self.projects = load_projects()
        states = scan_state_dir()
        result = []
        for sid, state in states.items():
            pname = project_name_from_cwd(state.get('cwd', ''), self.projects)
            state['_project_name'] = pname
            result.append(state)

        order = {'waiting': 0, 'working': 1, 'idle': 2}
        result.sort(key=lambda s: order.get(s.get('status', ''), 3))

        total_registered = len(self.projects)
        total_active = len(result)
        waiting_count = sum(1 for s in result if s.get('status') == 'waiting')

        table = Table(
            show_header=True,
            header_style="bold dim",
            box=None,
            padding=(0, 1),
            expand=True,
        )
        table.add_column("", width=2, no_wrap=True)
        table.add_column("Project", style="bold", ratio=2, no_wrap=True)
        table.add_column("Status", width=10, no_wrap=True)
        table.add_column("Message", ratio=3)
        table.add_column("Time", width=10, no_wrap=True, style="dim")

        if result:
            for s in result:
                status = s.get('status', 'unknown')
                ts = s.get('timestamp', '')
                stale = is_stale(ts)

                if stale:
                    icon = '⏸'
                elif status == 'working':
                    icon = '●'
                elif status == 'waiting':
                    icon = '●'
                elif status == 'idle':
                    icon = '○'
                else:
                    icon = '✕'

                if status == 'working':
                    icon_style = "bold dodger_blue1"
                elif status == 'waiting':
                    icon_style = "bold yellow"
                elif stale:
                    icon_style = "dim"
                else:
                    icon_style = "dim white"

                status_style = {
                    'working': 'dodger_blue1',
                    'waiting': 'bold yellow',
                    'idle': 'dim',
                }.get(status, 'red')

                pname = s['_project_name']
                msg = s.get('message', '')
                if len(msg) > 45:
                    msg = msg[:42] + '...'
                ago = time_ago(ts)

                table.add_row(
                    Text(icon, style=icon_style),
                    Text(pname),
                    Text(status, style=status_style),
                    Text(msg, style="italic" if status == 'waiting' else ""),
                    Text(ago),
                )
        else:
            # Show registered projects as offline
            for p in self.projects:
                table.add_row(
                    Text('✕', style='dim red'),
                    Text(p['name']),
                    Text('offline', style='dim red'),
                    Text(''),
                    Text(''),
                )

        title = f"Sessions — {total_registered} registered, {total_active} active"
        if waiting_count > 0:
            title += f" [bold yellow]({waiting_count} waiting)[/]"

        panel = Panel(
            table,
            title=f"[bold]{title}[/]",
            border_style="bright_cyan",
            padding=(0, 1),
        )
        self.update(panel)


class OutputLog(RichLog):
    """Area for displaying command output and notifications."""
    pass


class CommandInput(Input):
    """Command input widget."""
    pass


class HubestApp(App):
    """Hubest TUI App."""

    TITLE = "Hubest"
    SUB_TITLE = f"Claude Code Session Manager v{VERSION}"

    CSS = """
    Screen {
        background: $surface;
    }

    #sessions-panel {
        height: auto;
        max-height: 14;
        margin: 0 1;
    }

    #output-log {
        height: 1fr;
        margin: 0 1;
        border: round $primary-lighten-2;
        padding: 0 1;
        scrollbar-size: 1 1;
    }

    #output-log:focus {
        border: round $accent;
    }

    #input-container {
        height: 3;
        margin: 0 1 1 1;
    }

    #command-input {
        border: round $accent;
        padding: 0 1;
        background: $surface-darken-1;
    }

    #command-input:focus {
        border: round $accent-lighten-1;
        background: $surface;
    }

    Footer {
        background: $primary-background;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Exit", priority=True),
        Binding("ctrl+l", "clear_output", "Clear", priority=True),
        Binding("escape", "focus_input", "Input", priority=True),
    ]

    def __init__(self):
        super().__init__()
        self.projects = load_projects()
        self.known_states = {}
        self._pending_selection = None  # (options_list, callback, message)
        self._command_history = []
        self._history_idx = -1

    def compose(self) -> ComposeResult:
        yield Header()
        yield SessionsPanel(id="sessions-panel")
        yield OutputLog(id="output-log", highlight=True, markup=True)
        with Vertical(id="input-container"):
            yield CommandInput(
                placeholder="Enter a command or message...",
                id="command-input",
            )
        yield Footer()

    def on_mount(self):
        self.set_interval(1, self._background_watcher)
        log = self.query_one("#output-log", OutputLog)
        log.write(Text("Welcome to Hubest!", style="bold bright_cyan"))
        log.write(Text("Type 'help' or '?' to see available commands.", style="dim"))
        log.write("")
        self.query_one("#command-input").focus()

    def action_focus_input(self):
        self.query_one("#command-input").focus()

    def action_clear_output(self):
        self.query_one("#output-log", OutputLog).clear()

    def _log(self, *args, **kwargs):
        """Write to OutputLog."""
        self.query_one("#output-log", OutputLog).write(*args, **kwargs)

    def _log_text(self, text, style=""):
        self._log(Text(text, style=style))

    def _refresh_projects(self):
        self.projects = load_projects()
        self.query_one("#sessions-panel", SessionsPanel).refresh_display()

    # --- Input Handling ---

    def on_input_submitted(self, event: Input.Submitted):
        if event.input.id != "command-input":
            return
        raw = event.value.strip()
        event.input.value = ""

        if not raw:
            return

        # Save to history
        self._command_history.append(raw)
        self._history_idx = -1

        # Handle pending number selection
        if self._pending_selection is not None:
            self._handle_selection(raw)
            return

        self._log(Text(f"❯ {raw}", style="bold green"))
        self._handle_command(raw)

    def _handle_command(self, raw_input):
        # @mention
        if raw_input.startswith('@'):
            self._handle_mention(raw_input)
            return

        parts = raw_input.split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ''
        cmd = COMMAND_ALIASES.get(cmd, cmd)

        handler = getattr(self, f'cmd_{cmd}', None)
        if handler:
            handler(args)
        else:
            self._route_natural_language(raw_input)

    def _handle_mention(self, raw_input):
        match = re.match(r'@(\S+)\s*(.*)', raw_input)
        if not match:
            self._log_text("Usage: @project message", "yellow")
            return
        target = match.group(1)
        message = match.group(2) or ''
        project = find_project_by_name(target, self.projects)
        if project:
            if message:
                self._send_to_session(project, message)
            else:
                self._log_text(f"→ Switching to {project['name']} tab", "dim")
                iterm2_switch_tab(project['name'])
        else:
            self._log_text(f"Project \"{target}\" not found.", "red")

    def _route_natural_language(self, message):
        matches = []
        msg_lower = message.lower()
        for project in self.projects:
            for keyword in project.get('keywords', []):
                if keyword.lower() in msg_lower:
                    if project not in matches:
                        matches.append(project)
                    break

        if len(matches) == 1:
            self._send_to_session(matches[0], message)
        elif len(matches) > 1:
            self._log_text("Multiple projects matched:", "yellow")
            self._show_selection(matches, lambda p: self._send_to_session(p, message))
        else:
            if not self.projects:
                self._log_text("No projects registered. Use add <name> <path> to register.", "red")
                return
            self._log_text("Which project should receive this?", "yellow")
            self._show_selection(self.projects, lambda p: self._send_to_session(p, message))

    def _show_selection(self, items, callback):
        """Enter number selection mode."""
        for i, p in enumerate(items, 1):
            self._log(Text(f"  {i}) {p['name']}", style="bold"))
        self._log_text("Enter a number (Enter: cancel)", "dim")
        self._pending_selection = (items, callback)
        self.query_one("#command-input").placeholder = "Select number..."

    def _handle_selection(self, raw):
        items, callback = self._pending_selection
        self._pending_selection = None
        self.query_one("#command-input").placeholder = "Enter a command or message..."

        if not raw:
            self._log_text("Cancelled", "dim")
            return

        try:
            idx = int(raw) - 1
            if 0 <= idx < len(items):
                callback(items[idx])
            else:
                self._log_text("Invalid number", "red")
        except ValueError:
            self._log_text("Cancelled", "dim")
            # Non-numeric input, reprocess as a regular command
            self._log(Text(f"❯ {raw}", style="bold green"))
            self._handle_command(raw)

    def _send_to_session(self, project, message):
        success = iterm2_send_text(project['name'], message)
        if success:
            self._log_text(f"✓ Sent to {project['name']}", "green")
        else:
            # Tab not found, auto-create and retry
            self._log_text(f"⏳ Creating {project['name']} tab + starting Claude Code...", "dim")
            if iterm2_create_tab(project['name'], project.get('path', '')):
                self._log_text(f"✓ {project['name']} tab created — waiting to deliver message...", "green")
                self._retry_send_async(project['name'], message)
            else:
                self._log_text(f"✕ Failed to create {project['name']} tab", "red")

    @work(thread=True)
    def _retry_send_async(self, project_name, message):
        """Wait for Claude Code to start, then deliver message (background)."""
        import time
        for attempt in range(10):
            time.sleep(3)
            if iterm2_send_text(project_name, message):
                self.call_from_thread(
                    self._log_text, f"✓ Message delivered to {project_name}", "green"
                )
                return
        self.call_from_thread(
            self._log_text, f"⚠ {project_name} — Failed to deliver message. Please send manually: {message}", "yellow"
        )

    def _get_states_with_projects(self):
        states = scan_state_dir()
        result = []
        for sid, state in states.items():
            pname = project_name_from_cwd(state.get('cwd', ''), self.projects)
            state['_project_name'] = pname
            result.append(state)
        order = {'waiting': 0, 'working': 1, 'idle': 2}
        result.sort(key=lambda s: order.get(s.get('status', ''), 3))
        return result

    # ─── Background Watcher ───

    def _background_watcher(self):
        try:
            current = scan_state_dir()
            for sid, state in current.items():
                old = self.known_states.get(sid)
                new_status = state.get('status', '')
                old_status = old.get('status', '') if old else ''
                pname = project_name_from_cwd(state.get('cwd', ''), self.projects)
                msg = state.get('message', '')

                # New waiting state, or waiting message changed
                if (new_status == 'waiting'
                    and (old_status != 'waiting'
                         or old.get('timestamp') != state.get('timestamp') if old else True)):
                    self._log(Text(f"⚡ [{pname}] Waiting for input: {msg or 'Waiting for input'}", style="bold yellow"))
                    self.bell()

                # working → idle transition: task complete notification + show content
                elif new_status == 'idle' and old_status == 'working':
                    from rich.rule import Rule
                    self._log(Rule(f" ✅ {pname} — Task complete ", style="green"))
                    if msg:
                        self._log(Text(msg))
                    else:
                        self._log(Text("(no content)", style="dim"))
                    self._log(Rule(style="green"))
                    self._log(Text(""))
                    self.bell()

            self.known_states = current
        except Exception:
            pass

    # --- Command Handlers ---

    def cmd_status(self, args=''):
        states = self._get_states_with_projects()
        total_reg = len(self.projects)
        total_active = len(states)
        waiting = sum(1 for s in states if s.get('status') == 'waiting')

        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("icon", width=2)
        table.add_column("name", width=20)
        table.add_column("status", width=10)
        table.add_column("message")
        table.add_column("time", width=10)

        if states:
            for s in states:
                st = s.get('status', 'unknown')
                ts = s.get('timestamp', '')
                stale = is_stale(ts)
                icon = '⏸' if stale else {'working': '●', 'waiting': '●', 'idle': '○'}.get(st, '✕')
                icon_style = {
                    'working': 'dodger_blue1', 'waiting': 'yellow', 'idle': 'dim'
                }.get(st, 'red') if not stale else 'dim'
                status_style = {
                    'working': 'dodger_blue1', 'waiting': 'bold yellow', 'idle': 'dim'
                }.get(st, 'red')
                msg = s.get('message', '')[:42]
                table.add_row(
                    Text(icon, style=icon_style),
                    Text(s['_project_name'], style="bold"),
                    Text(st, style=status_style),
                    Text(msg, style="italic" if st == 'waiting' else ""),
                    Text(time_ago(ts), style="dim"),
                )
        else:
            for p in self.projects:
                table.add_row(
                    Text('✕', style='dim red'),
                    Text(p['name'], style='bold'),
                    Text('offline', style='dim red'),
                    Text(''), Text(''),
                )
            if not self.projects:
                self._log_text("No projects registered", "dim")
                return

        self._log(Panel(
            table,
            title=f"[bold]Session Status ({total_reg} registered, {total_active} active)[/]",
            border_style="bright_cyan",
            padding=(0, 1),
        ))

        if waiting > 0:
            self._log_text(f"🔔 {waiting} waiting for input — type 'p' to view", "yellow")

    def cmd_pending(self, args=''):
        states = self._get_states_with_projects()
        waiting = [s for s in states if s.get('status') == 'waiting']

        if not waiting:
            self._log_text("✓ No sessions waiting for input.", "green")
            return

        for i, s in enumerate(waiting, 1):
            pname = s['_project_name']
            msg = s.get('message', 'Waiting for input')
            ago = time_ago(s.get('timestamp', ''))
            panel = Panel(
                Text.assemble(
                    (f"\"{msg}\"\n", "italic"),
                    (f"Waiting: {ago}", "dim"),
                ),
                title=f"[bold yellow]{i}) {pname}[/]",
                border_style="yellow",
                padding=(0, 1),
            )
            self._log(panel)

        self._show_selection(
            [{'name': s['_project_name']} for s in waiting],
            lambda p: self._do_switch(p['name']),
        )

    def _do_switch(self, name):
        if iterm2_switch_tab(name):
            self._log_text(f"✓ Switched to {name} tab", "green")
        else:
            self._log_text(f"⚠ Tab for {name} not found.", "yellow")

    def cmd_switch(self, args=''):
        if args:
            project = find_project_by_name(args.strip(), self.projects)
            if project:
                self._do_switch(project['name'])
            else:
                self._log_text(f"Project \"{args.strip()}\" not found.", "red")
            return

        states = self._get_states_with_projects()
        items = []
        active_names = set()

        for s in states:
            pname = s['_project_name']
            items.append({'name': pname, 'status': s.get('status', 'unknown')})
            active_names.add(pname)

        for p in self.projects:
            if p['name'] not in active_names:
                items.append({'name': p['name'], 'status': 'offline'})

        if not items:
            self._log_text("No projects registered.", "dim")
            return

        for i, item in enumerate(items, 1):
            st = item['status']
            icon = {'working': '●', 'waiting': '●', 'idle': '○', 'offline': '✕'}.get(st, '?')
            color = {'working': 'dodger_blue1', 'waiting': 'yellow', 'idle': 'dim', 'offline': 'red'}.get(st, 'dim')
            self._log(Text.assemble(
                (f"  {i}) ", "bold"),
                (f"{icon} ", color),
                (f"{item['name']}  ", "bold"),
                (st, color),
            ))

        self._show_selection(items, lambda p: self._do_switch(p['name']))

    def cmd_send(self, args=''):
        if not args:
            self._log_text("Usage: send <project> <message>", "yellow")
            return
        parts = args.split(maxsplit=1)
        if len(parts) < 2:
            self._log_text("Usage: send <project> <message>", "yellow")
            return
        target, message = parts
        project = find_project_by_name(target, self.projects)
        if project:
            self._send_to_session(project, message)
        else:
            self._log_text(f"Project \"{target}\" not found.", "red")

    def cmd_start(self, args=''):
        if args:
            project = find_project_by_name(args.strip(), self.projects)
            if project:
                self._log_text(f"⏳ Starting {project['name']} session...", "dim")
                if iterm2_create_tab(project['name'], project['path']):
                    self._log_text(f"✓ {project['name']} tab created", "green")
                else:
                    self._log_text(f"✕ Failed to create tab", "red")
            else:
                self._log_text(f"Project \"{args.strip()}\" not found.", "red")
            return

        if not self.projects:
            self._log_text("No projects registered.", "red")
            return

        self._log_text(f"⏳ Starting sessions for {len(self.projects)} projects...", "dim")
        for p in self.projects:
            if iterm2_create_tab(p['name'], p['path']):
                self._log_text(f"  ✓ {p['name']}", "green")
            else:
                self._log_text(f"  ✕ {p['name']} — failed", "red")

    def cmd_stop(self, args=''):
        if args:
            project = find_project_by_name(args.strip(), self.projects)
            if project:
                states = scan_state_dir()
                cleaned = 0
                for sid, state in states.items():
                    pname = project_name_from_cwd(state.get('cwd', ''), self.projects)
                    if pname == project['name']:
                        sf = STATE_DIR / f'{sid}.json'
                        if sf.exists():
                            sf.unlink()
                            cleaned += 1
                self._log_text(f"✓ {project['name']} — {cleaned} state file(s) cleaned", "green")
                self._log_text("  Please close Claude Code in the iTerm2 tab manually.", "dim")
            else:
                self._log_text(f"Project \"{args.strip()}\" not found.", "red")
            return

        states = scan_state_dir()
        if not states:
            self._log_text("No state files to clean", "dim")
            return
        for sid in states:
            sf = STATE_DIR / f'{sid}.json'
            if sf.exists():
                sf.unlink()
        self._log_text(f"✓ {len(states)} state file(s) cleaned", "green")

    def cmd_dash(self, args=''):
        """Dashboard — session panel auto-refreshes in TUI, so just show status."""
        self._log_text("Session panel auto-refreshes every 2 seconds.", "dim")
        self.cmd_status()

    def cmd_projects(self, args=''):
        self._refresh_projects()
        if not self.projects:
            self._log_text("No projects registered. Use add <name> <path> to register.", "dim")
            return

        table = Table(show_header=True, header_style="bold dim", box=None, padding=(0, 1))
        table.add_column("Project", style="bold")
        table.add_column("Path")
        table.add_column("Keywords", style="italic")

        for p in self.projects:
            kws = ', '.join(p.get('keywords', []))
            table.add_row(p['name'], p.get('path', ''), kws)

        self._log(Panel(
            table,
            title=f"[bold]Registered Projects ({len(self.projects)})[/]",
            border_style="bright_cyan",
            padding=(0, 1),
        ))

    def cmd_add(self, args=''):
        if not args:
            self._log_text("Usage: add <name> <path> [--global]", "yellow")
            return
        parts = args.split()
        use_global = '--global' in parts
        parts = [p for p in parts if p != '--global']
        if len(parts) < 2:
            self._log_text("Usage: add <name> <path> [--global]", "yellow")
            return

        name, path = parts[0], parts[1]
        expanded_path = str(Path(path).expanduser().resolve())
        if not os.path.isdir(expanded_path):
            self._log_text(f"Directory does not exist: {expanded_path}", "red")
            return

        projects = load_projects()
        for p in projects:
            if p['name'] == name:
                self._log_text(f"Project \"{name}\" is already registered.", "yellow")
                return

        keywords = [name]
        if '-' in name:
            keywords.extend(name.split('-'))
        dirname = os.path.basename(expanded_path)
        if dirname != name and dirname not in keywords:
            keywords.append(dirname)

        project = {'name': name, 'path': path, 'keywords': keywords}
        projects.append(project)
        save_projects(projects)
        self._log_text(f"✓ Project registered: {name} → {path}", "green")
        self._log_text(f"  Keywords: {', '.join(keywords)}", "dim")

        if use_global:
            settings_path = Path.home() / '.claude' / 'settings.json'
        else:
            settings_path = Path(expanded_path) / '.claude' / 'settings.json'
        merge_hooks_into_settings(settings_path)
        self._log_text(f"  Hooks injected: {settings_path}", "dim")
        self._refresh_projects()

    def cmd_layout(self, args=''):
        self._log_text("Layout feature is not yet implemented.", "dim")

    def cmd_logs(self, args=''):
        self._log_text("Logs feature is not yet implemented.", "dim")

    def cmd_help(self, args=''):
        help_table = Table(show_header=False, box=None, padding=(0, 1))
        help_table.add_column("cmd", style="bold bright_cyan", width=14)
        help_table.add_column("alias", style="dim", width=6)
        help_table.add_column("desc")

        cmds = [
            ("status",   "s",  "Show all session statuses"),
            ("pending",  "p",  "View waiting sessions + switch"),
            ("switch",   "sw", "Switch to a session"),
            ("send",     "",   "Send message to a project"),
            ("start",    "",   "Start session (create iTerm2 tab)"),
            ("stop",     "",   "Stop session + clean state"),
            ("dash",     "d",  "Refresh session status"),
            ("projects", "pr", "List registered projects"),
            ("add",      "",   "Register a project"),
            ("clear",    "cls","Clear output (Ctrl+L)"),
            ("help",     "?,h","Show this help"),
            ("exit",     "q",  "Exit (Ctrl+C)"),
        ]
        for c, a, d in cmds:
            help_table.add_row(c, a, d)

        self._log(Panel(
            Group(
                help_table,
                Text(""),
                Text.assemble(
                    ("Natural language", "bold"),
                    (" — type a sentence with keywords to auto-route to the matching project", ""),
                ),
                Text.assemble(
                    ("@project message", "bold bright_cyan"),
                    (" — explicitly target a project to send a message", ""),
                ),
            ),
            title="[bold]Hubest Commands[/]",
            border_style="bright_cyan",
            padding=(1, 2),
        ))

    def cmd_exit(self, args=''):
        self._log_text("Sessions will persist. Goodbye!", "dim")
        self.exit()

    def cmd_clear(self, args=''):
        self.action_clear_output()


# --- Main ---

def main():
    if len(sys.argv) < 2:
        sys.argv.append('interactive')

    command = sys.argv[1]

    if command == 'init':
        cmd_init()
    elif command == 'add':
        args = ' '.join(sys.argv[2:])
        cmd_add_oneshot(args)
    elif command == 'help':
        print()
        print('  Hubest — Claude Code Multi-Session Manager')
        print()
        print('  Usage:')
        print('    hubest              Launch TUI')
        print('    hubest init         Initial setup')
        print('    hubest add <n> <p>  Register a project')
        print('    hubest --version    Show version')
        print('    hubest --help       Show this help')
        print()
    elif command == 'interactive':
        app = HubestApp()
        app.run()
    else:
        print(f'  Unknown command: {command}')

if __name__ == '__main__':
    main()
