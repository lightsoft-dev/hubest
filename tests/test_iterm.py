"""Tests for iTerm2 integration with subprocess mocking."""

from unittest.mock import patch, MagicMock
import subprocess

import hubest_cli


class TestIterm2SwitchTab:
    @patch("hubest_cli.subprocess.run")
    def test_found_returns_true(self, mock_run):
        mock_run.return_value = MagicMock(stdout="found\n", returncode=0)
        result = hubest_cli.iterm2_switch_tab("myapp")
        assert result is True
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert call_args[0][0][0] == "osascript"

    @patch("hubest_cli.subprocess.run")
    def test_not_found_returns_false(self, mock_run):
        mock_run.return_value = MagicMock(stdout="not_found\n", returncode=0)
        result = hubest_cli.iterm2_switch_tab("nonexistent")
        assert result is False

    @patch("hubest_cli.subprocess.run")
    def test_subprocess_error_returns_false(self, mock_run):
        mock_run.side_effect = subprocess.SubprocessError("failed")
        result = hubest_cli.iterm2_switch_tab("myapp")
        assert result is False

    @patch("hubest_cli.subprocess.run")
    def test_file_not_found_returns_false(self, mock_run):
        mock_run.side_effect = FileNotFoundError("osascript not found")
        result = hubest_cli.iterm2_switch_tab("myapp")
        assert result is False

    @patch("hubest_cli.subprocess.run")
    def test_script_contains_project_name(self, mock_run):
        mock_run.return_value = MagicMock(stdout="found\n", returncode=0)
        hubest_cli.iterm2_switch_tab("my-project")
        call_args = mock_run.call_args
        script = call_args[0][0][2]  # osascript -e <script>
        assert "hubest:my-project" in script


class TestIterm2SendText:
    @patch("hubest_cli.subprocess.run")
    def test_found_returns_true(self, mock_run):
        mock_run.return_value = MagicMock(stdout="found\n", returncode=0)
        result = hubest_cli.iterm2_send_text("myapp", "hello world")
        assert result is True

    @patch("hubest_cli.subprocess.run")
    def test_not_found_returns_false(self, mock_run):
        mock_run.return_value = MagicMock(stdout="not_found\n", returncode=0)
        result = hubest_cli.iterm2_send_text("nonexistent", "hello")
        assert result is False

    @patch("hubest_cli.subprocess.run")
    def test_script_contains_text(self, mock_run):
        mock_run.return_value = MagicMock(stdout="found\n", returncode=0)
        hubest_cli.iterm2_send_text("myapp", "test message")
        call_args = mock_run.call_args
        script = call_args[0][0][2]
        assert "test message" in script

    @patch("hubest_cli.subprocess.run")
    def test_subprocess_error_returns_false(self, mock_run):
        mock_run.side_effect = subprocess.SubprocessError("fail")
        result = hubest_cli.iterm2_send_text("myapp", "msg")
        assert result is False


class TestIterm2CreateTab:
    @patch("hubest_cli.subprocess.run")
    def test_success_returns_true(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        result = hubest_cli.iterm2_create_tab("myapp", "/Users/test/myapp")
        assert result is True

    @patch("hubest_cli.subprocess.run")
    def test_subprocess_error_returns_false(self, mock_run):
        mock_run.side_effect = subprocess.SubprocessError("fail")
        result = hubest_cli.iterm2_create_tab("myapp", "/path")
        assert result is False

    @patch("hubest_cli.subprocess.run")
    def test_file_not_found_returns_false(self, mock_run):
        mock_run.side_effect = FileNotFoundError("osascript not found")
        result = hubest_cli.iterm2_create_tab("myapp", "/path")
        assert result is False

    @patch("hubest_cli.subprocess.run")
    def test_script_contains_project_name_and_path(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        hubest_cli.iterm2_create_tab("myapp", "/Users/test/myapp")
        call_args = mock_run.call_args
        script = call_args[0][0][2]
        assert "hubest:myapp" in script
        # Path should be expanded/resolved but still contain the base
        assert "myapp" in script


class TestFindItermSession:
    @patch("hubest_cli.subprocess.run")
    def test_found_returns_true(self, mock_run):
        mock_run.return_value = MagicMock(stdout="found\n", returncode=0)
        result = hubest_cli._find_iterm_session("myapp")
        assert result is True

    @patch("hubest_cli.subprocess.run")
    def test_not_found_returns_false(self, mock_run):
        mock_run.return_value = MagicMock(stdout="not_found\n", returncode=0)
        result = hubest_cli._find_iterm_session("myapp")
        assert result is False

    @patch("hubest_cli.subprocess.run")
    def test_error_returns_false(self, mock_run):
        mock_run.side_effect = subprocess.SubprocessError("fail")
        result = hubest_cli._find_iterm_session("myapp")
        assert result is False
