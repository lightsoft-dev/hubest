"""Shared fixtures for hubest tests."""

import json
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pytest

# Ensure the project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hubest_cli


@pytest.fixture
def temp_hubest_dir(tmp_path):
    """Create a temp directory structure mimicking ~/.hubest/ with state/ subdirectory."""
    hubest_dir = tmp_path / ".hubest"
    hubest_dir.mkdir()
    (hubest_dir / "state").mkdir()
    (hubest_dir / "hooks").mkdir()
    return hubest_dir


@pytest.fixture
def mock_hubest_paths(monkeypatch, temp_hubest_dir):
    """Monkeypatch HUBEST_DIR, STATE_DIR, PROJECTS_FILE in hubest_cli module."""
    monkeypatch.setattr(hubest_cli, "HUBEST_DIR", temp_hubest_dir)
    monkeypatch.setattr(hubest_cli, "STATE_DIR", temp_hubest_dir / "state")
    monkeypatch.setattr(hubest_cli, "PROJECTS_FILE", temp_hubest_dir / "projects.yaml")
    return temp_hubest_dir


@pytest.fixture
def sample_projects():
    """Return a list of project dicts for testing."""
    return [
        {
            "name": "myapp",
            "path": "/Users/test/myapp",
            "keywords": ["app", "frontend"],
        },
        {
            "name": "backend-api",
            "path": "/Users/test/backend-api",
            "keywords": ["backend-api", "backend", "api", "server"],
        },
        {
            "name": "docs",
            "path": "/Users/test/docs",
            "keywords": ["docs", "documentation"],
        },
    ]


@pytest.fixture
def sample_state_files(temp_hubest_dir):
    """Write sample JSON state files to the temp state dir and return their paths."""
    state_dir = temp_hubest_dir / "state"
    now = datetime.now(timezone.utc)

    files = {}

    # Working session
    working = {
        "session_id": "sess-001",
        "status": "working",
        "cwd": "/Users/test/myapp",
        "timestamp": now.isoformat(),
        "message": "Running tests",
    }
    p = state_dir / "sess-001.json"
    p.write_text(json.dumps(working))
    files["working"] = p

    # Waiting session
    waiting = {
        "session_id": "sess-002",
        "status": "waiting",
        "cwd": "/Users/test/backend-api",
        "timestamp": (now - timedelta(minutes=5)).isoformat(),
        "message": "Need API key",
    }
    p = state_dir / "sess-002.json"
    p.write_text(json.dumps(waiting))
    files["waiting"] = p

    # Idle session
    idle = {
        "session_id": "sess-003",
        "status": "idle",
        "cwd": "/Users/test/docs",
        "timestamp": (now - timedelta(hours=2)).isoformat(),
        "message": "",
    }
    p = state_dir / "sess-003.json"
    p.write_text(json.dumps(idle))
    files["idle"] = p

    return files
