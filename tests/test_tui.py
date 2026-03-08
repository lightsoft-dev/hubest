"""Basic TUI tests using Textual's pilot."""

import pytest
from unittest.mock import patch

import hubest_cli
from hubest_cli import HubestApp


@pytest.fixture
def mock_load_projects():
    """Mock load_projects to return empty list so TUI doesn't touch real filesystem."""
    with patch.object(hubest_cli, "load_projects", return_value=[]):
        with patch.object(hubest_cli, "scan_state_dir", return_value={}):
            yield


@pytest.mark.asyncio
async def test_app_mounts(mock_load_projects):
    """App should mount successfully without errors."""
    app = HubestApp()
    async with app.run_test() as pilot:
        # App should be running
        assert app.is_running

        # Key widgets should exist
        sessions_panel = app.query_one("#sessions-panel")
        assert sessions_panel is not None

        output_log = app.query_one("#output-log")
        assert output_log is not None

        command_input = app.query_one("#command-input")
        assert command_input is not None


@pytest.mark.asyncio
async def test_escape_focuses_input(mock_load_projects):
    """Pressing Escape should focus the command input."""
    app = HubestApp()
    async with app.run_test() as pilot:
        # Focus something else first
        app.query_one("#output-log").focus()
        await pilot.press("escape")
        assert app.query_one("#command-input").has_focus


@pytest.mark.asyncio
async def test_ctrl_l_clears_output(mock_load_projects):
    """Ctrl+L should trigger clear action without error."""
    app = HubestApp()
    async with app.run_test() as pilot:
        log = app.query_one("#output-log", hubest_cli.OutputLog)
        # Write something, then clear
        log.write("test line")
        await pilot.press("ctrl+l")
        # After clear, the log's internal lines should be empty
        assert len(log.lines) == 0
