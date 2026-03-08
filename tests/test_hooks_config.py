"""Tests for hook configuration in hubest_cli."""

import json
from pathlib import Path

import hubest_cli


class TestMergeHooksIntoSettings:
    def test_empty_settings_file(self, tmp_path):
        settings_path = tmp_path / ".claude" / "settings.json"
        hubest_cli.merge_hooks_into_settings(str(settings_path))

        assert settings_path.exists()
        with open(settings_path) as f:
            data = json.load(f)
        assert "hooks" in data
        # Should have all event types from HOOKS_CONFIG
        for event in hubest_cli.HOOKS_CONFIG["hooks"]:
            assert event in data["hooks"]

    def test_nonexistent_file_creates_it(self, tmp_path):
        settings_path = tmp_path / "deep" / "nested" / "settings.json"
        hubest_cli.merge_hooks_into_settings(str(settings_path))
        assert settings_path.exists()

    def test_creates_parent_directories(self, tmp_path):
        settings_path = tmp_path / "new_dir" / ".claude" / "settings.json"
        hubest_cli.merge_hooks_into_settings(str(settings_path))
        assert settings_path.parent.exists()
        assert settings_path.exists()

    def test_idempotent(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        hubest_cli.merge_hooks_into_settings(str(settings_path))
        with open(settings_path) as f:
            first = json.load(f)

        hubest_cli.merge_hooks_into_settings(str(settings_path))
        with open(settings_path) as f:
            second = json.load(f)

        # Running twice should produce the same result
        assert first == second

    def test_preserves_existing_hooks(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        existing = {
            "hooks": {
                "Notification": [
                    {
                        "matcher": "",
                        "hooks": [
                            {
                                "type": "command",
                                "command": "/custom/hook.sh",
                                "timeout": 5,
                            }
                        ],
                    }
                ]
            }
        }
        with open(settings_path, "w") as f:
            json.dump(existing, f)

        hubest_cli.merge_hooks_into_settings(str(settings_path))

        with open(settings_path) as f:
            data = json.load(f)

        # Original hook should still be there
        notif_hooks = data["hooks"]["Notification"]
        commands = []
        for entry in notif_hooks:
            for h in entry.get("hooks", []):
                commands.append(h.get("command"))
        assert "/custom/hook.sh" in commands

    def test_preserves_other_settings(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        existing = {"some_key": "some_value", "nested": {"a": 1}}
        with open(settings_path, "w") as f:
            json.dump(existing, f)

        hubest_cli.merge_hooks_into_settings(str(settings_path))

        with open(settings_path) as f:
            data = json.load(f)

        assert data["some_key"] == "some_value"
        assert data["nested"]["a"] == 1
        assert "hooks" in data

    def test_handles_invalid_json_in_existing_file(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        settings_path.write_text("{bad json")

        hubest_cli.merge_hooks_into_settings(str(settings_path))

        with open(settings_path) as f:
            data = json.load(f)
        assert "hooks" in data

    def test_all_hook_events_present(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        hubest_cli.merge_hooks_into_settings(str(settings_path))

        with open(settings_path) as f:
            data = json.load(f)

        expected_events = [
            "Notification",
            "Stop",
            "SessionStart",
            "SessionEnd",
            "PostToolUse",
        ]
        for event in expected_events:
            assert event in data["hooks"], f"Missing hook event: {event}"
