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
    'l': 'last',
}

SLASH_COMMANDS = {
    'add': 'Add a project to track',
}

CLAUDE_CLI = Path.home() / '.claude' / 'local' / 'claude'

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
    os.makedirs(os.path.dirname(path), exist_ok=True)
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

def ensure_hubest_setup():
    """Ensure ~/.hubest directories and hook scripts exist. Auto-init if needed."""
    dirs = [HUBEST_DIR, STATE_DIR, HUBEST_DIR / 'hooks']
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

    # Copy hook scripts from the repo's hooks/ dir (sibling to this script)
    repo_hooks = Path(__file__).resolve().parent / 'hooks'
    if repo_hooks.is_dir():
        dest_hooks = HUBEST_DIR / 'hooks'
        for src in repo_hooks.glob('*.sh'):
            dest = dest_hooks / src.name
            if not dest.exists() or src.stat().st_mtime > dest.stat().st_mtime:
                shutil.copy2(src, dest)
                os.chmod(dest, 0o755)

    # Copy skill files to ~/.claude/skills/
    repo_skills = Path(__file__).resolve().parent / 'skills'
    if repo_skills.is_dir():
        claude_skills = Path.home() / '.claude' / 'skills'
        for skill_dir in repo_skills.iterdir():
            if skill_dir.is_dir():
                dest_skill = claude_skills / skill_dir.name
                dest_skill.mkdir(parents=True, exist_ok=True)
                for src in skill_dir.iterdir():
                    if src.is_file():
                        dest = dest_skill / src.name
                        if not dest.exists() or src.stat().st_mtime > dest.stat().st_mtime:
                            shutil.copy2(src, dest)

    # Sync hubest_cli.py itself to ~/.hubest/ (skills reference it)
    src_cli = Path(__file__).resolve()
    dest_cli = HUBEST_DIR / 'hubest_cli.py'
    if src_cli != dest_cli:
        if not dest_cli.exists() or src_cli.stat().st_mtime > dest_cli.stat().st_mtime:
            shutil.copy2(src_cli, dest_cli)


def ai_route_message(message, projects):
    """Use claude -p to determine which project(s) a message should be routed to.
    Returns a list of matching project dicts, or empty list if no match / error."""
    if not projects or not CLAUDE_CLI.exists():
        return []

    project_list = '\n'.join(
        f'- name: "{p["name"]}", path: "{p.get("path","")}", keywords: {p.get("keywords",[])}'
        for p in projects
    )

    prompt = f"""You are a message router. Given a user message and a list of projects, determine which project(s) the message should be sent to.

Projects:
{project_list}

User message: "{message}"

Rules:
- Return ONLY a JSON array of project names that match. Example: ["project-a"]
- If the message is relevant to multiple projects, return all matching names.
- If you cannot determine the target, return [].
- Do NOT include any explanation, only the JSON array."""

    try:
        env = os.environ.copy()
        env.pop('CLAUDECODE', None)
        result = subprocess.run(
            [str(CLAUDE_CLI), '-p', prompt,
             '--output-format', 'json',
             '--model', 'haiku',
             '--max-turns', '1',
             '--no-session-persistence'],
            capture_output=True, text=True, timeout=15, env=env,
        )
        if result.returncode != 0:
            return []

        # Parse the JSON output from claude -p --output-format json
        outer = json.loads(result.stdout)
        content = outer.get('result', '') if isinstance(outer, dict) else str(outer)

        # Extract JSON array from the content
        match = re.search(r'\[.*?\]', content, re.DOTALL)
        if not match:
            return []
        names = json.loads(match.group())
        if not names:
            return []

        matched = []
        for n in names:
            for p in projects:
                if p['name'].lower() == n.lower() and p not in matched:
                    matched.append(p)
        return matched
    except (subprocess.SubprocessError, json.JSONDecodeError, Exception):
        return []


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
    """Send text to existing hubest:{project_name} session.
    Text and Enter are sent as separate osascript calls to avoid
    bracketed paste swallowing the newline in TUI apps like Claude Code."""
    target_title = f'hubest:{project_name}'
    escaped_text = text.replace('\\', '\\\\').replace('"', '\\"')
    # Step 1: Send text without trailing newline
    text_script = f'''
    tell application "iTerm2"
        repeat with w in windows
            repeat with t in tabs of w
                tell current session of t
                    if name contains "{target_title}" then
                        write text "{escaped_text}" without newline
                        return "found"
                    end if
                end tell
            end repeat
        end repeat
        return "not_found"
    end tell
    '''
    try:
        result = subprocess.run(['osascript', '-e', text_script], capture_output=True, timeout=5, text=True)
        if result.stdout.strip() != 'found':
            return False
    except (subprocess.SubprocessError, FileNotFoundError):
        return False

    # Step 2: Send Enter as a separate event
    import time
    time.sleep(0.2)
    enter_script = f'''
    tell application "iTerm2"
        repeat with w in windows
            repeat with t in tabs of w
                tell current session of t
                    if name contains "{target_title}" then
                        write text ""
                        return "ok"
                    end if
                end tell
            end repeat
        end repeat
    end tell
    '''
    try:
        subprocess.run(['osascript', '-e', enter_script], capture_output=True, timeout=5, text=True)
    except subprocess.SubprocessError:
        pass
    return True

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
    # Install skills to ~/.claude/skills/
    repo_skills = Path(__file__).resolve().parent / 'skills'
    if repo_skills.is_dir():
        claude_skills = Path.home() / '.claude' / 'skills'
        for skill_dir in repo_skills.iterdir():
            if skill_dir.is_dir():
                dest_skill = claude_skills / skill_dir.name
                dest_skill.mkdir(parents=True, exist_ok=True)
                for src in skill_dir.iterdir():
                    if src.is_file():
                        shutil.copy2(src, dest_skill / src.name)
                print(f'  ✅ Skill installed: {dest_skill}')
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
    print('  Next steps:')
    print('    hubest add <name> <path>  Register a project (name + path)')
    print('    hubest register           Register current dir')
    print('    /hubest-add               Register from any Claude Code session')
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


def cmd_register(args=''):
    """Register a project by path (defaults to cwd). Standalone, no TUI dependency."""
    ensure_hubest_setup()
    parts = args.split() if args else []
    use_global = '--global' in parts
    parts = [p for p in parts if p != '--global']

    path = parts[0] if parts else os.getcwd()
    expanded_path = str(Path(path).expanduser().resolve())
    if not os.path.isdir(expanded_path):
        print(f'Error: Directory does not exist: {expanded_path}')
        sys.exit(1)

    projects = load_projects()

    # Check if already registered by path
    for p in projects:
        existing_path = str(Path(p.get('path', '')).expanduser().resolve())
        if existing_path == expanded_path:
            print(f'Already registered: {p["name"]} -> {expanded_path}')
            print(f'Keywords: {p.get("keywords", [])}')
            return

    # Auto-derive name from basename
    name = os.path.basename(expanded_path)

    # If name already exists, use parent/basename format
    existing_names = {p['name'] for p in projects}
    if name in existing_names:
        parent = os.path.basename(os.path.dirname(expanded_path))
        name = f"{parent}/{name}" if parent else name
        if name in existing_names:
            print(f'Error: Project name "{name}" is already taken.')
            sys.exit(1)

    keywords = [name]
    basename = os.path.basename(expanded_path)
    if basename != name and basename not in keywords:
        keywords.append(basename)
    if '-' in name:
        keywords.extend(name.split('-'))

    project = {'name': name, 'path': expanded_path, 'keywords': keywords}
    projects.append(project)
    save_projects(projects)
    print(f'Project registered: {name} -> {expanded_path}')
    print(f'Keywords: {", ".join(keywords)}')

    if use_global:
        settings_path = Path.home() / '.claude' / 'settings.json'
    else:
        settings_path = Path(expanded_path) / '.claude' / 'settings.json'
    merge_hooks_into_settings(settings_path)
    print(f'Hooks injected: {settings_path}')


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


class ProjectsSidebar(Static):
    """Left sidebar showing all registered projects with status indicators.
    Supports selecting Hub (broadcast) or a single project as message target."""

    COMPONENT_CLASSES = {"sidebar--selected"}

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.projects = load_projects()
        self.selected = "hub"  # "hub" or project name
        self._project_names = []  # ordered list for navigation

    def on_mount(self):
        self.set_interval(2, self.refresh_display)
        self.refresh_display()

    def select(self, name):
        """Select Hub or a project by name."""
        self.selected = name
        self.refresh_display()

    def select_next(self):
        """Move selection down."""
        all_items = ["hub"] + self._project_names
        try:
            idx = all_items.index(self.selected)
        except ValueError:
            idx = 0
        self.selected = all_items[min(idx + 1, len(all_items) - 1)]
        self.refresh_display()

    def select_prev(self):
        """Move selection up."""
        all_items = ["hub"] + self._project_names
        try:
            idx = all_items.index(self.selected)
        except ValueError:
            idx = 0
        self.selected = all_items[max(idx - 1, 0)]
        self.refresh_display()

    def refresh_display(self):
        self.projects = load_projects()
        states = scan_state_dir()

        # Map sessions to projects by cwd
        project_status = {}
        for sid, state in states.items():
            pname = project_name_from_cwd(state.get('cwd', ''), self.projects)
            if pname and pname != 'unknown':
                existing = project_status.get(pname)
                priority = {'waiting': 0, 'working': 1, 'idle': 2}
                if existing is None or priority.get(state.get('status', ''), 3) < priority.get(existing, 3):
                    project_status[pname] = state.get('status', 'idle')

        self._project_names = [p.get('name', '?') for p in self.projects]

        # Validate selection still exists
        if self.selected != "hub" and self.selected not in self._project_names:
            self.selected = "hub"

        lines = []

        # Hub entry at top
        active_count = sum(1 for s in project_status.values() if s in ('working', 'idle', 'waiting'))
        if self.selected == "hub":
            lines.append(Text.assemble(
                (" ▸ ", "bold bright_cyan"),
                ("Hub", "bold bright_cyan"),
                (f"  ({active_count})", "dim"),
            ))
        else:
            lines.append(Text.assemble(
                ("   ", ""),
                ("Hub", "bold"),
                (f"  ({active_count})", "dim"),
            ))

        # Separator
        lines.append(Text("  ──────────────────", style="dim"))

        if not self.projects:
            lines.append(Text("  (no projects)", style="dim"))
        else:
            for p in self.projects:
                name = p.get('name', '?')
                status = project_status.get(name, 'offline')

                if status == 'working':
                    icon = '●'
                    icon_style = "bold dodger_blue1"
                elif status == 'waiting':
                    icon = '●'
                    icon_style = "bold yellow"
                elif status == 'idle':
                    icon = '○'
                    icon_style = "dim white"
                else:
                    icon = '·'
                    icon_style = "dim red"

                display_name = name[:14]
                is_selected = (self.selected == name)

                status_label = {
                    'working': ' working',
                    'waiting': ' waiting',
                    'idle': ' idle',
                }.get(status, '')
                status_label_style = {
                    'working': 'dodger_blue1',
                    'waiting': 'yellow',
                    'idle': 'dim',
                }.get(status, 'dim red')

                if is_selected:
                    lines.append(Text.assemble(
                        (" ▸ ", "bold bright_cyan"),
                        (f"{icon} ", icon_style),
                        (display_name, "bold bright_cyan"),
                        (status_label, status_label_style),
                    ))
                elif status in ('working', 'waiting'):
                    lines.append(Text.assemble(
                        ("   ", ""),
                        (f"{icon} ", icon_style),
                        (display_name, "bold"),
                        (status_label, status_label_style),
                    ))
                else:
                    lines.append(Text.assemble(
                        ("   ", ""),
                        (f"{icon} ", icon_style),
                        (display_name, icon_style),
                        (status_label, status_label_style),
                    ))

        content = Group(*lines)
        self.update(Panel(
            content,
            title="[bold]Projects[/]",
            border_style="bright_cyan",
            padding=(0, 1),
        ))


class OutputLog(RichLog):
    """Area for displaying command output and notifications."""
    pass


class SlashPopup(Static):
    """Popup showing available slash commands above the input."""

    def update_commands(self, filter_text=''):
        """Update displayed commands based on filter text."""
        matches = []
        for cmd, desc in SLASH_COMMANDS.items():
            if cmd.startswith(filter_text):
                matches.append((cmd, desc))

        if not matches:
            self.display = False
            return

        self.display = True
        lines = []
        for cmd, desc in matches:
            lines.append(Text.assemble(
                ("  /", "bold bright_cyan"),
                (cmd, "bold bright_cyan"),
                (f"  {desc}", "dim"),
            ))
        self.update(Group(*lines))

    def hide(self):
        self.display = False


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

    #sidebar {
        dock: left;
        width: 24;
        height: 100%;
        margin: 0 0 0 1;
    }

    #slash-popup {
        height: auto;
        max-height: 6;
        margin: 0 1;
        display: none;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Exit", priority=True),
        Binding("ctrl+l", "clear_output", "Clear", priority=True),
        Binding("ctrl+b", "toggle_sidebar", "Sidebar", priority=True),
        Binding("ctrl+j", "sidebar_next", "Next", priority=True),
        Binding("ctrl+k", "sidebar_prev", "Prev", priority=True),
        Binding("escape", "focus_input", "Input", priority=True),
    ]

    def __init__(self):
        super().__init__()
        self.projects = load_projects()
        self.known_states = {}
        self._pending_selection = None  # (options_list, callback, message)
        self._command_history = []
        self._history_idx = -1
        self._last_responses = {}  # project_name → full response text

    def compose(self) -> ComposeResult:
        yield Header()
        yield ProjectsSidebar(id="sidebar")
        yield OutputLog(id="output-log", highlight=True, markup=True)
        yield SlashPopup(id="slash-popup")
        with Vertical(id="input-container"):
            yield CommandInput(
                placeholder="Enter a command or message...",
                id="command-input",
            )
        yield Footer()

    def on_mount(self):
        ensure_hubest_setup()
        self.set_interval(1, self._background_watcher)
        log = self.query_one("#output-log", OutputLog)
        log.write(Text("Welcome to Hubest!", style="bold bright_cyan"))
        log.write(Text("Type 'help' or '?' to see available commands.", style="dim"))
        log.write("")
        self.query_one("#command-input").focus()

    def on_input_changed(self, event: Input.Changed):
        if event.input.id != "command-input":
            return
        value = event.value
        popup = self.query_one("#slash-popup", SlashPopup)
        if value.startswith('/'):
            # Extract the command part (text after / up to first space)
            after_slash = value[1:].split(' ', 1)[0]
            popup.update_commands(after_slash)
        else:
            popup.hide()

    def action_focus_input(self):
        self.query_one("#command-input").focus()

    def action_clear_output(self):
        self.query_one("#output-log", OutputLog).clear()

    def action_toggle_sidebar(self):
        sidebar = self.query_one("#sidebar", ProjectsSidebar)
        sidebar.display = not sidebar.display

    def action_sidebar_next(self):
        self.query_one("#sidebar", ProjectsSidebar).select_next()
        self._update_input_placeholder()
        self._switch_to_selected_project()

    def action_sidebar_prev(self):
        self.query_one("#sidebar", ProjectsSidebar).select_prev()
        self._update_input_placeholder()
        self._switch_to_selected_project()

    def _update_input_placeholder(self):
        sidebar = self.query_one("#sidebar", ProjectsSidebar)
        inp = self.query_one("#command-input")
        if sidebar.selected == "hub":
            inp.placeholder = "Type a message (AI will route to the right project)..."
        else:
            inp.placeholder = f"Message {sidebar.selected}..."

    @work(thread=True)
    def _switch_to_selected_project(self):
        sidebar = self.query_one("#sidebar", ProjectsSidebar)
        if sidebar.selected != "hub":
            iterm2_switch_tab(sidebar.selected)

    def _log(self, *args, **kwargs):
        """Write to OutputLog."""
        self.query_one("#output-log", OutputLog).write(*args, **kwargs)

    def _log_text(self, text, style=""):
        self._log(Text(text, style=style))

    def _refresh_projects(self):
        self.projects = load_projects()
        self.query_one("#sidebar", ProjectsSidebar).refresh_display()

    # --- Input Handling ---

    def on_input_submitted(self, event: Input.Submitted):
        if event.input.id != "command-input":
            return
        raw = event.value.strip()
        event.input.value = ""
        self.query_one("#slash-popup", SlashPopup).hide()

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
        # Slash commands
        if raw_input.startswith('/'):
            self._handle_slash_command(raw_input)
            return

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
        sidebar = self.query_one("#sidebar", ProjectsSidebar)

        # If a specific project is selected in the sidebar, send directly
        if sidebar.selected != "hub":
            self._refresh_projects()
            project = find_project_by_name(sidebar.selected, self.projects)
            if project:
                self._send_to_session(project, message)
                return
            self._log_text(f"Project \"{sidebar.selected}\" not found.", "red")
            return

        # Hub mode: use AI to route to matching project(s)
        self._refresh_projects()
        if not self.projects:
            self._log_text("No projects registered. Use /add <path> to register.", "yellow")
            return

        self._log_text("🔍 Analyzing message to find target project(s)...", "dim")
        self._ai_route_async(message)

    @work(thread=True)
    def _ai_route_async(self, message):
        """Run AI routing in background thread to keep TUI responsive."""
        projects = load_projects()
        matched = ai_route_message(message, projects)

        if not matched:
            self.call_from_thread(
                self._log_text,
                "Could not determine target project. Use Ctrl+J/K to select a project first, or @project message.",
                "yellow",
            )
            return

        names = ', '.join(p['name'] for p in matched)
        self.call_from_thread(
            self._log_text, f"→ AI routed to: {names}", "bright_cyan"
        )
        for p in matched:
            self.call_from_thread(self._send_to_session, p, message)

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
        """Wait for Claude Code to be ready, then deliver message."""
        import time
        projects = load_projects()
        project = find_project_by_name(project_name, projects)
        project_path = str(Path(project['path']).expanduser().resolve()) if project else None

        # Strategy 1: Check state file from SessionStart hook (if hooks are installed)
        # Strategy 2: Fall back to timed retry after initial wait for Claude Code startup
        initial_wait = True
        for attempt in range(30):
            time.sleep(1)
            # Check if SessionStart hook created a state file
            if project_path:
                states = scan_state_dir()
                for sid, state in states.items():
                    cwd = str(Path(state.get('cwd', '')).expanduser().resolve())
                    if cwd == project_path and state.get('status') in ('idle', 'waiting'):
                        if iterm2_send_text(project_name, message):
                            self.call_from_thread(
                                self._log_text, f"✓ Message delivered to {project_name}", "green"
                            )
                            return
            # After 8 seconds, start trying to send directly (hooks may not be installed)
            if attempt >= 7 and initial_wait:
                initial_wait = False
            if not initial_wait and attempt % 3 == 0:
                if iterm2_send_text(project_name, message):
                    self.call_from_thread(
                        self._log_text, f"✓ Message delivered to {project_name}", "green"
                    )
                    return

        self.call_from_thread(
            self._log_text, f"⚠ {project_name} — Failed to deliver. Please send manually: {message}", "yellow"
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
            from rich.rule import Rule
            current = scan_state_dir()
            for sid, state in current.items():
                old = self.known_states.get(sid)
                new_status = state.get('status', '')
                old_status = old.get('status', '') if old else ''
                new_ts = state.get('timestamp', '')
                old_ts = old.get('timestamp', '') if old else ''
                pname = project_name_from_cwd(state.get('cwd', ''), self.projects)
                msg = state.get('message', '')

                # New waiting state, or waiting message changed
                if (new_status == 'waiting'
                    and (old_status != 'waiting' or new_ts != old_ts)):
                    self._log(Text(f"⚡ [{pname}] Waiting for input: {msg or 'Waiting for input'}", style="bold yellow"))
                    self.bell()

                # Task complete: idle with new/changed content
                elif new_status == 'idle' and msg and (
                    old_status == 'working'
                    or old is None
                    or new_ts != old_ts
                ):
                    self._last_responses[pname] = msg
                    lines = msg.split('\n')
                    preview = '\n'.join(lines[:5])
                    truncated = len(lines) > 5
                    self._log(Rule(f" ✅ {pname} — Task complete ", style="green"))
                    self._log(Text(preview))
                    if truncated:
                        self._log(Text(f"  ... ({len(lines) - 5} more lines — type 'last {pname}' to see full)", style="dim"))
                    self._log(Rule(style="green"))
                    self._log(Text(""))
                    self.bell()

                # Status change notification (working started)
                elif new_status == 'working' and old_status != 'working':
                    self._log_text(f"⏳ [{pname}] Working...", "dodger_blue1")

            self.known_states = current
        except Exception:
            pass

    # --- Slash Command Handlers ---

    def _handle_slash_command(self, raw_input):
        """Parse and dispatch slash commands."""
        # Hide popup
        self.query_one("#slash-popup", SlashPopup).hide()

        stripped = raw_input[1:]  # remove leading /
        parts = stripped.split(maxsplit=1)
        cmd = parts[0].lower() if parts else ''
        args = parts[1] if len(parts) > 1 else ''

        if not cmd:
            self._log_text("Type a command after /. Try /help or /add <path>", "yellow")
            return

        handler = getattr(self, f'slash_{cmd}', None)
        if handler:
            handler(args)
        else:
            self._log_text(f"Unknown command: /{cmd}", "red")
            available = ', '.join(f'/{c}' for c in SLASH_COMMANDS)
            self._log_text(f"  Available: {available}", "dim")

    def slash_add(self, args=''):
        """Add a project by path. Name is auto-derived from directory basename."""
        ensure_hubest_setup()
        if not args:
            self._log_text("Usage: /add <path> [--global]", "yellow")
            return

        parts = args.split()
        use_global = '--global' in parts
        parts = [p for p in parts if p != '--global']
        if not parts:
            self._log_text("Usage: /add <path> [--global]", "yellow")
            return

        path = parts[0]
        expanded_path = str(Path(path).expanduser().resolve())
        if not os.path.isdir(expanded_path):
            self._log_text(f"Directory does not exist: {expanded_path}", "red")
            return

        # Auto-derive name from basename
        name = os.path.basename(expanded_path)

        # If name already exists, use parent/dirname format
        projects = load_projects()
        existing_names = {p['name'] for p in projects}
        if name in existing_names:
            parent = os.path.basename(os.path.dirname(expanded_path))
            name = f"{parent}/{name}" if parent else name
            if name in existing_names:
                self._log_text(f"Project \"{name}\" is already registered.", "yellow")
                return

        keywords = [name]
        basename = os.path.basename(expanded_path)
        if basename != name and basename not in keywords:
            keywords.append(basename)
        if '-' in name:
            keywords.extend(name.split('-'))

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

    def cmd_last(self, args=''):
        """Show the full last response from a project."""
        if args:
            name = args.strip()
            # Try exact match first, then partial
            msg = self._last_responses.get(name)
            if not msg:
                for pname, resp in self._last_responses.items():
                    if name.lower() in pname.lower():
                        msg = resp
                        name = pname
                        break
            if msg:
                from rich.rule import Rule
                from rich.markdown import Markdown
                self._log(Rule(f" {name} — Full Response ", style="bright_cyan"))
                self._log(Markdown(msg))
                self._log(Rule(style="bright_cyan"))
            else:
                self._log_text(f"No response stored for \"{args.strip()}\".", "yellow")
        else:
            if not self._last_responses:
                self._log_text("No responses yet.", "dim")
                return
            # Show most recent response
            name = list(self._last_responses.keys())[-1]
            msg = self._last_responses[name]
            from rich.rule import Rule
            from rich.markdown import Markdown
            self._log(Rule(f" {name} — Full Response ", style="bright_cyan"))
            self._log(Markdown(msg))
            self._log(Rule(style="bright_cyan"))

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
            ("last",     "l",  "Show full last response"),
            ("clear",    "cls","Clear output (Ctrl+L)"),
            ("help",     "?,h","Show this help"),
            ("exit",     "q",  "Exit (Ctrl+C)"),
        ]
        for c, a, d in cmds:
            help_table.add_row(c, a, d)

        # Slash commands section
        slash_table = Table(show_header=False, box=None, padding=(0, 1))
        slash_table.add_column("cmd", style="bold bright_cyan", width=20)
        slash_table.add_column("desc")
        for cmd, desc in SLASH_COMMANDS.items():
            slash_table.add_row(f"/{cmd}", desc)

        self._log(Panel(
            Group(
                help_table,
                Text(""),
                Text("Slash Commands", style="bold underline"),
                slash_table,
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
    elif command == 'register':
        args = ' '.join(sys.argv[2:])
        cmd_register(args)
    elif command == 'help':
        print()
        print('  Hubest — Claude Code Multi-Session Manager')
        print()
        print('  Usage:')
        print('    hubest              Launch TUI')
        print('    hubest init         Initial setup')
        print('    hubest add <n> <p>  Register a project (name + path)')
        print('    hubest register [p] Register current dir (or path)')
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
