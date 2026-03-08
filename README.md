# Hubest

iTerm2 + Claude Code Hooks 기반의 멀티 프로젝트 세션 매니저 TUI.

여러 프로젝트에서 동시에 Claude Code를 실행하고, 하나의 터미널에서 전체 세션을 모니터링·제어할 수 있습니다.

```
┌──────────────── Hubest ──────────────────────┐
│ Sessions — 3 registered, 2 active            │
│  ● fabric-mall     working  Tool: Write  12s │
│  ● moonlight       waiting  검토해주세요  3m  │
│  ○ erp-config      idle                 15m  │
├──────────────────────────────────────────────┤
│ ❯ status                                     │
│ ──── ✅ moonlight — 작업 완료 ────           │
│ 파일을 수정했습니다...                         │
│ ─────────────────────────────────            │
│                                              │
│ ⚡ [moonlight] 입력 대기: 파일 삭제 허용?     │
├──────────────────────────────────────────────┤
│ 명령어 또는 메시지를 입력하세요...              │
└──────────────────────────────────────────────┘
```

## 요구사항

- **macOS** (iTerm2 전용)
- **iTerm2**
- **Python 3.8+**
- **jq** — hook 스크립트에서 JSON 처리
- **Claude Code** — 관리 대상

## 설치

```bash
# 1. 클론
git clone https://github.com/lightsoft-dev/hubest.git
cd hubest

# 2. Python 의존성 설치
pip3 install textual rich pyyaml

# 3. ~/.hubest 에 파일 배포
mkdir -p ~/.hubest/{state,iterm,bin}
cp hubest_cli.py ~/.hubest/
cp hubest ~/.hubest/bin/
cp -r hooks/ ~/.hubest/hooks/
chmod +x ~/.hubest/bin/hubest ~/.hubest/hooks/*.sh

# 4. PATH 추가 (~/.zshrc 또는 ~/.bashrc)
echo 'export PATH="$HOME/.hubest/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc

# 5. 초기화
hubest init
```

## 프로젝트 등록

```bash
# 프로젝트별 .claude/settings.json 에 hooks 주입
hubest add moonlight ~/projects/moonlight-alley
hubest add fabric ~/projects/fabric-shopping-mall
hubest add erp ~/projects/ecount-erp

# 또는 글로벌 hooks (모든 프로젝트에 자동 적용)
hubest add moonlight ~/projects/moonlight-alley --global
```

등록하면 해당 프로젝트의 `.claude/settings.json`에 hubest hooks가 자동 주입됩니다.
`--global` 옵션을 사용하면 `~/.claude/settings.json`에 한번만 추가하면 됩니다.

등록 후 `~/.hubest/projects.yaml`에서 키워드를 편집할 수 있습니다:

```yaml
projects:
  - name: moonlight
    path: ~/projects/moonlight-alley
    keywords: ["moonlight", "문라이트", "앨리"]
  - name: fabric
    path: ~/projects/fabric-shopping-mall
    keywords: ["원단", "쇼핑몰", "fabric"]
```

## 사용법

```bash
hubest          # TUI 실행
```

### TUI 명령어

| 명령어 | 축약 | 설명 |
|--------|------|------|
| `status` | `s` | 전체 세션 상태 표시 |
| `pending` | `p` | 입력 대기 세션 확인 + 번호로 탭 전환 |
| `switch <project>` | `sw` | iTerm2 탭 전환 |
| `send <project> <msg>` | | 프로젝트에 메시지 전달 |
| `start [project]` | | iTerm2 탭 생성 + Claude Code 실행 |
| `stop [project]` | | 세션 상태 정리 |
| `dash` | `d` | 세션 상태 새로고침 |
| `projects` | `pr` | 등록된 프로젝트 목록 |
| `add <name> <path>` | | 프로젝트 등록 |
| `help` | `h`, `?` | 도움말 |
| `exit` | `q` | TUI 종료 (Claude Code 세션은 유지) |
| `clear` | `cls`, `Ctrl+L` | 출력 정리 |

### 자연어 라우팅

내장 명령어가 아닌 입력은 자연어로 간주하고, `projects.yaml`의 키워드와 매칭하여 해당 프로젝트의 Claude Code 세션에 전달합니다.

```
hubest> 원단 결제 모듈 수정해줘        → 키워드 "원단" → fabric 세션에 전달
hubest> @moonlight 챕터 3 정리해줘     → @멘션 → moonlight 세션에 전달
hubest> 데이터베이스 마이그레이션 실행   → 매칭 실패 → 프로젝트 선택 프롬프트
```

### 실시간 알림

Claude Code가 입력을 기다리거나 작업을 완료하면, TUI에 실시간으로 알림이 표시됩니다:

- `⚡ [project] 입력 대기: ...` — 권한 요청 등
- `✅ [project] 작업 완료` — 구분선과 함께 응답 내용 표시

## 동작 원리

```
Claude Code 세션 → Hook 이벤트 발생
                 → on-*.sh 스크립트가 ~/.hubest/state/{session_id}.json 기록
                 → hubest TUI가 1초마다 state 디렉토리 감시
                 → 상태 변화 감지 시 세션 패널 갱신 + 알림 표시
```

Hook 이벤트 5종:

| Hook | 상태 | 설명 |
|------|------|------|
| `SessionStart` | idle | 세션 시작 |
| `PostToolUse` | working | 도구 사용 중 |
| `Notification` | waiting | 사용자 입력 대기 |
| `Stop` | idle | 응답 완료 (마지막 응답 내용 저장) |
| `SessionEnd` | — | 세션 종료 (상태 파일 삭제) |

## 디렉토리 구조

```
~/.hubest/
├── bin/hubest           # 엔트리포인트
├── hubest_cli.py        # 메인 TUI 앱
├── hooks/               # Claude Code Hook 스크립트
│   ├── on-notification.sh
│   ├── on-stop.sh
│   ├── on-session-start.sh
│   ├── on-session-end.sh
│   └── on-activity.sh
├── state/               # 세션 상태 (hooks가 기록)
├── projects.yaml        # 프로젝트 등록 정보
├── config.yaml          # 설정
└── history              # 명령어 히스토리
```

## License

MIT
