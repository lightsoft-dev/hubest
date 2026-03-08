"""Tests for state scanning in hubest_cli."""

import json
from pathlib import Path

import hubest_cli


class TestScanStateDir:
    def test_valid_json_files(self, mock_hubest_paths, sample_state_files):
        states = hubest_cli.scan_state_dir()
        assert len(states) == 3
        assert "sess-001" in states
        assert "sess-002" in states
        assert "sess-003" in states

    def test_reads_correct_data(self, mock_hubest_paths, sample_state_files):
        states = hubest_cli.scan_state_dir()
        assert states["sess-001"]["status"] == "working"
        assert states["sess-002"]["status"] == "waiting"
        assert states["sess-003"]["status"] == "idle"

    def test_invalid_json_files_skipped(self, mock_hubest_paths, temp_hubest_dir):
        state_dir = temp_hubest_dir / "state"
        # Write an invalid JSON file
        (state_dir / "bad.json").write_text("{not valid json!!!")
        # Write a valid one
        (state_dir / "good.json").write_text(
            json.dumps({"session_id": "good", "status": "idle"})
        )
        states = hubest_cli.scan_state_dir()
        assert len(states) == 1
        assert "good" in states

    def test_hidden_files_skipped(self, mock_hubest_paths, temp_hubest_dir):
        state_dir = temp_hubest_dir / "state"
        (state_dir / ".hidden.json").write_text(
            json.dumps({"session_id": "hidden", "status": "idle"})
        )
        (state_dir / "visible.json").write_text(
            json.dumps({"session_id": "visible", "status": "idle"})
        )
        states = hubest_cli.scan_state_dir()
        assert len(states) == 1
        assert "visible" in states
        assert "hidden" not in states

    def test_non_json_files_skipped(self, mock_hubest_paths, temp_hubest_dir):
        state_dir = temp_hubest_dir / "state"
        (state_dir / "readme.txt").write_text("not a state file")
        (state_dir / "valid.json").write_text(
            json.dumps({"session_id": "valid", "status": "idle"})
        )
        states = hubest_cli.scan_state_dir()
        assert len(states) == 1
        assert "valid" in states

    def test_empty_directory(self, mock_hubest_paths):
        states = hubest_cli.scan_state_dir()
        assert states == {}

    def test_nonexistent_directory(self, monkeypatch, tmp_path):
        monkeypatch.setattr(hubest_cli, "STATE_DIR", tmp_path / "nonexistent")
        states = hubest_cli.scan_state_dir()
        assert states == {}

    def test_session_id_from_data(self, mock_hubest_paths, temp_hubest_dir):
        """session_id should come from data, not filename."""
        state_dir = temp_hubest_dir / "state"
        (state_dir / "filename.json").write_text(
            json.dumps({"session_id": "from-data", "status": "idle"})
        )
        states = hubest_cli.scan_state_dir()
        assert "from-data" in states

    def test_missing_session_id_uses_stem(self, mock_hubest_paths, temp_hubest_dir):
        """If session_id is missing from data, use file stem."""
        state_dir = temp_hubest_dir / "state"
        (state_dir / "fallback.json").write_text(
            json.dumps({"status": "idle"})
        )
        states = hubest_cli.scan_state_dir()
        assert "fallback" in states
