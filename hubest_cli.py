#!/usr/bin/env python3
"""Hubest — Claude Code 멀티세션 매니저 TUI"""

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

# ─── YAML 유틸 ───

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

# ─── 유틸리티 함수 ───

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
            return '방금'
        if seconds < 60:
            return f'{seconds}초 전'
        minutes = seconds // 60
        if minutes < 60:
            return f'{minutes}분 전'
        hours = minutes // 60
        if hours < 24:
            return f'{hours}시간 전'
        days = hours // 24
        return f'{days}일 전'
    except (ValueError, TypeError):
        return '알 수 없음'

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
    """hubest:{project_name}을 포함하는 iTerm2 세션을 찾아 탭 인덱스 반환."""
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
    """기존 hubest:{project_name} 세션에 텍스트 전송. 탭 전환 없음."""
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
    """새 탭 생성 + Claude Code 실행. 포커스는 원래 탭으로 복귀."""
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

# ─── 원샷 명령어 ───

def cmd_init():
    print()
    print('  Hubest 초기 설정')
    print('  ' + '─' * 40)
    print()
    dirs = [HUBEST_DIR, STATE_DIR, HUBEST_DIR / 'hooks', HUBEST_DIR / 'iterm', HUBEST_DIR / 'bin']
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
        print(f'  ✅ {d}')
    if not PROJECTS_FILE.exists():
        _save_yaml(str(PROJECTS_FILE), {'projects': []})
        print(f'  ✅ {PROJECTS_FILE} (템플릿 생성)')
    else:
        print(f'  ⏭  {PROJECTS_FILE} (이미 존재)')
    if not CONFIG_FILE.exists():
        _save_yaml(str(CONFIG_FILE), {'stale_hours': 24, 'watch_interval': 1, 'version': VERSION})
        print(f'  ✅ {CONFIG_FILE}')
    else:
        print(f'  ⏭  {CONFIG_FILE} (이미 존재)')
    hooks_dir = HUBEST_DIR / 'hooks'
    for hf in ['on-notification.sh', 'on-stop.sh', 'on-session-start.sh', 'on-session-end.sh', 'on-activity.sh']:
        hp = hooks_dir / hf
        if hp.exists():
            os.chmod(hp, 0o755)
            print(f'  ✅ {hp} (chmod +x)')
        else:
            print(f'  ⚠️  {hp} 없음 — hubest를 재설치하세요')
    hubest_bin = HUBEST_DIR / 'bin' / 'hubest'
    if hubest_bin.exists():
        os.chmod(hubest_bin, 0o755)
        print(f'  ✅ {hubest_bin} (chmod +x)')
    print()
    print('  의존성 확인')
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
        print('  ⚠️  pyyaml 없음 (선택사항) — pip3 install pyyaml')
    print()
    if deps_ok:
        print('  ✅ 초기 설정 완료!')
    else:
        print('  ⚠️  누락된 의존성을 설치한 후 다시 실행하세요.')
    hubest_bin_dir = str(HUBEST_DIR / 'bin')
    if hubest_bin_dir not in os.environ.get('PATH', '').split(':'):
        print()
        print(f'  💡 PATH에 추가하세요:')
        print(f'     export PATH="$HOME/.hubest/bin:$PATH"')
    print()
    print('  다음 단계: hubest add <이름> <경로> 로 프로젝트를 등록하세요.')
    print()

def cmd_add_oneshot(args):
    parts = args.split()
    if len(parts) < 2:
        print('  사용법: hubest add <이름> <경로> [--global]')
        return
    use_global = '--global' in parts
    parts = [p for p in parts if p != '--global']
    _do_add_project(parts[0], parts[1], use_global)

def _do_add_project(name, path, use_global=False):
    expanded_path = str(Path(path).expanduser().resolve())
    if not os.path.isdir(expanded_path):
        print(f'  ❌ 디렉토리가 존재하지 않습니다: {expanded_path}')
        return
    projects = load_projects()
    for p in projects:
        if p['name'] == name:
            print(f'  ⚠️  "{name}" 프로젝트가 이미 등록되어 있습니다.')
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
    print(f'  ✅ 프로젝트 등록: {name} → {path}')
    print(f'     키워드: {keywords}')
    if use_global:
        settings_path = Path.home() / '.claude' / 'settings.json'
        merge_hooks_into_settings(settings_path)
        print(f'  ✅ 글로벌 hooks 주입: {settings_path}')
    else:
        settings_path = Path(expanded_path) / '.claude' / 'settings.json'
        merge_hooks_into_settings(settings_path)
        print(f'  ✅ 프로젝트 hooks 주입: {settings_path}')


# ─── Textual TUI ───

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
    """세션 상태를 실시간으로 표시하는 위젯."""

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
        table.add_column("프로젝트", style="bold", ratio=2, no_wrap=True)
        table.add_column("상태", width=10, no_wrap=True)
        table.add_column("메시지", ratio=3)
        table.add_column("시간", width=10, no_wrap=True, style="dim")

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
            # 등록된 프로젝트만 offline으로 표시
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
    """명령 출력 + 알림을 표시하는 영역."""
    pass


class CommandInput(Input):
    """명령어 입력 위젯."""
    pass


class HubestApp(App):
    """Hubest TUI 앱."""

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
        Binding("ctrl+c", "quit", "종료", priority=True),
        Binding("ctrl+l", "clear_output", "화면정리", priority=True),
        Binding("escape", "focus_input", "입력창", priority=True),
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
                placeholder="명령어 또는 메시지를 입력하세요...",
                id="command-input",
            )
        yield Footer()

    def on_mount(self):
        self.set_interval(1, self._background_watcher)
        log = self.query_one("#output-log", OutputLog)
        log.write(Text("Hubest에 오신 것을 환영합니다!", style="bold bright_cyan"))
        log.write(Text("'help' 또는 '?'를 입력하면 명령어 목록을 볼 수 있습니다.", style="dim"))
        log.write("")
        self.query_one("#command-input").focus()

    def action_focus_input(self):
        self.query_one("#command-input").focus()

    def action_clear_output(self):
        self.query_one("#output-log", OutputLog).clear()

    def _log(self, *args, **kwargs):
        """OutputLog에 출력."""
        self.query_one("#output-log", OutputLog).write(*args, **kwargs)

    def _log_text(self, text, style=""):
        self._log(Text(text, style=style))

    def _refresh_projects(self):
        self.projects = load_projects()
        self.query_one("#sessions-panel", SessionsPanel).refresh_display()

    # ─── 입력 처리 ───

    def on_input_submitted(self, event: Input.Submitted):
        if event.input.id != "command-input":
            return
        raw = event.value.strip()
        event.input.value = ""

        if not raw:
            return

        # 히스토리에 저장
        self._command_history.append(raw)
        self._history_idx = -1

        # 번호 선택 대기 중이면 처리
        if self._pending_selection is not None:
            self._handle_selection(raw)
            return

        self._log(Text(f"❯ {raw}", style="bold green"))
        self._handle_command(raw)

    def _handle_command(self, raw_input):
        # @멘션
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
            self._log_text("사용법: @프로젝트명 메시지", "yellow")
            return
        target = match.group(1)
        message = match.group(2) or ''
        project = find_project_by_name(target, self.projects)
        if project:
            if message:
                self._send_to_session(project, message)
            else:
                self._log_text(f"→ {project['name']} 탭으로 전환", "dim")
                iterm2_switch_tab(project['name'])
        else:
            self._log_text(f"프로젝트 \"{target}\"를 찾을 수 없습니다.", "red")

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
            self._log_text("여러 프로젝트가 매칭됩니다:", "yellow")
            self._show_selection(matches, lambda p: self._send_to_session(p, message))
        else:
            if not self.projects:
                self._log_text("등록된 프로젝트가 없습니다. add <이름> <경로>로 등록하세요.", "red")
                return
            self._log_text("어떤 프로젝트에 전달할까요?", "yellow")
            self._show_selection(self.projects, lambda p: self._send_to_session(p, message))

    def _show_selection(self, items, callback):
        """번호 선택 모드 진입."""
        for i, p in enumerate(items, 1):
            self._log(Text(f"  {i}) {p['name']}", style="bold"))
        self._log_text("번호를 입력하세요 (Enter: 취소)", "dim")
        self._pending_selection = (items, callback)
        self.query_one("#command-input").placeholder = "번호 선택..."

    def _handle_selection(self, raw):
        items, callback = self._pending_selection
        self._pending_selection = None
        self.query_one("#command-input").placeholder = "명령어 또는 메시지를 입력하세요..."

        if not raw:
            self._log_text("취소됨", "dim")
            return

        try:
            idx = int(raw) - 1
            if 0 <= idx < len(items):
                callback(items[idx])
            else:
                self._log_text("잘못된 번호", "red")
        except ValueError:
            self._log_text("취소됨", "dim")
            # 입력이 숫자가 아니면 일반 명령으로 재처리
            self._log(Text(f"❯ {raw}", style="bold green"))
            self._handle_command(raw)

    def _send_to_session(self, project, message):
        success = iterm2_send_text(project['name'], message)
        if success:
            self._log_text(f"✓ {project['name']} 에 전달됨", "green")
        else:
            # 탭이 없으면 자동 생성 후 메시지 전달 재시도
            self._log_text(f"⏳ {project['name']} 탭 생성 + Claude Code 시작 중...", "dim")
            if iterm2_create_tab(project['name'], project.get('path', '')):
                self._log_text(f"✓ {project['name']} 탭 생성됨 — 메시지 전달 대기 중...", "green")
                self._retry_send_async(project['name'], message)
            else:
                self._log_text(f"✕ {project['name']} 탭 생성 실패", "red")

    @work(thread=True)
    def _retry_send_async(self, project_name, message):
        """Claude Code 시작을 기다렸다가 메시지 전달 (백그라운드)."""
        import time
        for attempt in range(10):
            time.sleep(3)
            if iterm2_send_text(project_name, message):
                self.call_from_thread(
                    self._log_text, f"✓ {project_name} 에 메시지 전달됨", "green"
                )
                return
        self.call_from_thread(
            self._log_text, f"⚠ {project_name} — 메시지 전달 실패. 수동으로 전달하세요: {message}", "yellow"
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

                # 새로 waiting 상태가 됐거나, waiting 메시지가 바뀌었을 때
                if (new_status == 'waiting'
                    and (old_status != 'waiting'
                         or old.get('timestamp') != state.get('timestamp') if old else True)):
                    self._log(Text(f"⚡ [{pname}] 입력 대기: {msg or '입력 대기 중'}", style="bold yellow"))
                    self.bell()

                # working → idle 전환: 작업 완료 알림 + 내용 표시
                elif new_status == 'idle' and old_status == 'working':
                    from rich.rule import Rule
                    self._log(Rule(f" ✅ {pname} — 작업 완료 ", style="green"))
                    if msg:
                        self._log(Text(msg))
                    else:
                        self._log(Text("(내용 없음)", style="dim"))
                    self._log(Rule(style="green"))
                    self._log(Text(""))
                    self.bell()

            self.known_states = current
        except Exception:
            pass

    # ─── 명령어 핸들러 ───

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
                self._log_text("등록된 프로젝트 없음", "dim")
                return

        self._log(Panel(
            table,
            title=f"[bold]세션 상태 ({total_reg}개 등록, {total_active}개 활성)[/]",
            border_style="bright_cyan",
            padding=(0, 1),
        ))

        if waiting > 0:
            self._log_text(f"🔔 입력 대기 {waiting}건 — 'p'를 입력하여 확인", "yellow")

    def cmd_pending(self, args=''):
        states = self._get_states_with_projects()
        waiting = [s for s in states if s.get('status') == 'waiting']

        if not waiting:
            self._log_text("✓ 입력 대기 중인 세션이 없습니다.", "green")
            return

        for i, s in enumerate(waiting, 1):
            pname = s['_project_name']
            msg = s.get('message', '입력 대기 중')
            ago = time_ago(s.get('timestamp', ''))
            panel = Panel(
                Text.assemble(
                    (f"\"{msg}\"\n", "italic"),
                    (f"대기 시간: {ago}", "dim"),
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
            self._log_text(f"✓ {name} 탭으로 전환됨", "green")
        else:
            self._log_text(f"⚠ {name} 탭을 찾을 수 없습니다.", "yellow")

    def cmd_switch(self, args=''):
        if args:
            project = find_project_by_name(args.strip(), self.projects)
            if project:
                self._do_switch(project['name'])
            else:
                self._log_text(f"프로젝트 \"{args.strip()}\"를 찾을 수 없습니다.", "red")
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
            self._log_text("등록된 프로젝트가 없습니다.", "dim")
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
            self._log_text("사용법: send <프로젝트> <메시지>", "yellow")
            return
        parts = args.split(maxsplit=1)
        if len(parts) < 2:
            self._log_text("사용법: send <프로젝트> <메시지>", "yellow")
            return
        target, message = parts
        project = find_project_by_name(target, self.projects)
        if project:
            self._send_to_session(project, message)
        else:
            self._log_text(f"프로젝트 \"{target}\"를 찾을 수 없습니다.", "red")

    def cmd_start(self, args=''):
        if args:
            project = find_project_by_name(args.strip(), self.projects)
            if project:
                self._log_text(f"⏳ {project['name']} 세션 시작 중...", "dim")
                if iterm2_create_tab(project['name'], project['path']):
                    self._log_text(f"✓ {project['name']} 탭 생성됨", "green")
                else:
                    self._log_text(f"✕ 탭 생성 실패", "red")
            else:
                self._log_text(f"프로젝트 \"{args.strip()}\"를 찾을 수 없습니다.", "red")
            return

        if not self.projects:
            self._log_text("등록된 프로젝트가 없습니다.", "red")
            return

        self._log_text(f"⏳ {len(self.projects)}개 프로젝트 세션 시작 중...", "dim")
        for p in self.projects:
            if iterm2_create_tab(p['name'], p['path']):
                self._log_text(f"  ✓ {p['name']}", "green")
            else:
                self._log_text(f"  ✕ {p['name']} — 실패", "red")

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
                self._log_text(f"✓ {project['name']} 상태 파일 {cleaned}개 정리됨", "green")
                self._log_text("  iTerm2 탭의 Claude Code는 수동으로 종료하세요.", "dim")
            else:
                self._log_text(f"프로젝트 \"{args.strip()}\"를 찾을 수 없습니다.", "red")
            return

        states = scan_state_dir()
        if not states:
            self._log_text("정리할 상태 파일 없음", "dim")
            return
        for sid in states:
            sf = STATE_DIR / f'{sid}.json'
            if sf.exists():
                sf.unlink()
        self._log_text(f"✓ {len(states)}개 상태 파일 정리됨", "green")

    def cmd_dash(self, args=''):
        """대시보드 — TUI에서는 세션 패널이 이미 실시간이므로 status를 표시."""
        self._log_text("세션 패널이 2초마다 자동 갱신됩니다.", "dim")
        self.cmd_status()

    def cmd_projects(self, args=''):
        self._refresh_projects()
        if not self.projects:
            self._log_text("등록된 프로젝트가 없습니다. add <이름> <경로>로 등록하세요.", "dim")
            return

        table = Table(show_header=True, header_style="bold dim", box=None, padding=(0, 1))
        table.add_column("프로젝트", style="bold")
        table.add_column("경로")
        table.add_column("키워드", style="italic")

        for p in self.projects:
            kws = ', '.join(p.get('keywords', []))
            table.add_row(p['name'], p.get('path', ''), kws)

        self._log(Panel(
            table,
            title=f"[bold]등록된 프로젝트 ({len(self.projects)}개)[/]",
            border_style="bright_cyan",
            padding=(0, 1),
        ))

    def cmd_add(self, args=''):
        if not args:
            self._log_text("사용법: add <이름> <경로> [--global]", "yellow")
            return
        parts = args.split()
        use_global = '--global' in parts
        parts = [p for p in parts if p != '--global']
        if len(parts) < 2:
            self._log_text("사용법: add <이름> <경로> [--global]", "yellow")
            return

        name, path = parts[0], parts[1]
        expanded_path = str(Path(path).expanduser().resolve())
        if not os.path.isdir(expanded_path):
            self._log_text(f"디렉토리가 존재하지 않습니다: {expanded_path}", "red")
            return

        projects = load_projects()
        for p in projects:
            if p['name'] == name:
                self._log_text(f"\"{name}\" 프로젝트가 이미 등록되어 있습니다.", "yellow")
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
        self._log_text(f"✓ 프로젝트 등록: {name} → {path}", "green")
        self._log_text(f"  키워드: {', '.join(keywords)}", "dim")

        if use_global:
            settings_path = Path.home() / '.claude' / 'settings.json'
        else:
            settings_path = Path(expanded_path) / '.claude' / 'settings.json'
        merge_hooks_into_settings(settings_path)
        self._log_text(f"  hooks 주입: {settings_path}", "dim")
        self._refresh_projects()

    def cmd_layout(self, args=''):
        self._log_text("layout 기능은 향후 구현 예정입니다.", "dim")

    def cmd_logs(self, args=''):
        self._log_text("logs 기능은 향후 구현 예정입니다.", "dim")

    def cmd_help(self, args=''):
        help_table = Table(show_header=False, box=None, padding=(0, 1))
        help_table.add_column("cmd", style="bold bright_cyan", width=14)
        help_table.add_column("alias", style="dim", width=6)
        help_table.add_column("desc")

        cmds = [
            ("status",   "s",  "전체 세션 상태 표시"),
            ("pending",  "p",  "입력 대기 세션 확인 + 전환"),
            ("switch",   "sw", "세션 전환"),
            ("send",     "",   "프로젝트에 메시지 전달"),
            ("start",    "",   "세션 시작 (iTerm2 탭 생성)"),
            ("stop",     "",   "세션 종료 + 상태 정리"),
            ("dash",     "d",  "세션 상태 새로고침"),
            ("projects", "pr", "등록된 프로젝트 목록"),
            ("add",      "",   "프로젝트 등록"),
            ("clear",    "cls","출력 영역 정리 (Ctrl+L)"),
            ("help",     "?,h","이 도움말"),
            ("exit",     "q",  "종료 (Ctrl+C)"),
        ]
        for c, a, d in cmds:
            help_table.add_row(c, a, d)

        self._log(Panel(
            Group(
                help_table,
                Text(""),
                Text.assemble(
                    ("자연어 입력", "bold"),
                    (" — 키워드가 포함된 문장을 입력하면 자동으로 해당 프로젝트에 라우팅", ""),
                ),
                Text.assemble(
                    ("@프로젝트 메시지", "bold bright_cyan"),
                    (" — 명시적으로 프로젝트를 지정하여 메시지 전달", ""),
                ),
            ),
            title="[bold]Hubest 명령어[/]",
            border_style="bright_cyan",
            padding=(1, 2),
        ))

    def cmd_exit(self, args=''):
        self._log_text("세션은 유지됩니다. 안녕히!", "dim")
        self.exit()

    def cmd_clear(self, args=''):
        self.action_clear_output()


# ─── 메인 ───

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
        print('  Hubest — Claude Code 멀티세션 매니저')
        print()
        print('  사용법:')
        print('    hubest              TUI 진입')
        print('    hubest init         초기 설정')
        print('    hubest add <n> <p>  프로젝트 등록')
        print('    hubest --version    버전 표시')
        print('    hubest --help       이 도움말')
        print()
    elif command == 'interactive':
        app = HubestApp()
        app.run()
    else:
        print(f'  알 수 없는 명령: {command}')

if __name__ == '__main__':
    main()
