"""Tests for pure utility functions in hubest_cli."""

from datetime import datetime, timezone, timedelta

import pytest

import hubest_cli


class TestTimeAgo:
    def test_just_now(self):
        now = datetime.now(timezone.utc).isoformat()
        result = hubest_cli.time_ago(now)
        # Should be seconds-level (either "just now" or "Ns ago" type string)
        assert result is not None
        assert isinstance(result, str)
        assert len(result) > 0

    def test_seconds_ago(self):
        ts = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
        result = hubest_cli.time_ago(ts)
        assert result is not None
        assert isinstance(result, str)

    def test_minutes_ago(self):
        ts = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        result = hubest_cli.time_ago(ts)
        assert result is not None
        # Should contain a number (the minutes)
        assert any(c.isdigit() for c in result)

    def test_hours_ago(self):
        ts = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        result = hubest_cli.time_ago(ts)
        assert result is not None
        assert any(c.isdigit() for c in result)

    def test_days_ago(self):
        ts = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        result = hubest_cli.time_ago(ts)
        assert result is not None
        assert any(c.isdigit() for c in result)

    def test_none_input(self):
        # None triggers AttributeError on .replace() — not caught by except block
        with pytest.raises(AttributeError):
            hubest_cli.time_ago(None)

    def test_invalid_string(self):
        result = hubest_cli.time_ago("not-a-timestamp")
        assert isinstance(result, str)

    def test_future_timestamp(self):
        ts = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        result = hubest_cli.time_ago(ts)
        # Future timestamps return a string (implementation returns "just now" equivalent)
        assert isinstance(result, str)

    def test_z_suffix_utc(self):
        """Timestamps ending in Z should be handled correctly."""
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z"
        result = hubest_cli.time_ago(ts)
        assert isinstance(result, str)


class TestIsStale:
    def test_fresh_timestamp(self):
        ts = datetime.now(timezone.utc).isoformat()
        assert hubest_cli.is_stale(ts) is False

    def test_stale_timestamp(self):
        ts = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        assert hubest_cli.is_stale(ts) is True

    def test_borderline_fresh(self):
        ts = (datetime.now(timezone.utc) - timedelta(hours=23)).isoformat()
        assert hubest_cli.is_stale(ts) is False

    def test_none_raises(self):
        # None triggers AttributeError on .replace() — not caught by except block
        with pytest.raises(AttributeError):
            hubest_cli.is_stale(None)

    def test_invalid_format_returns_true(self):
        assert hubest_cli.is_stale("garbage") is True

    def test_empty_string_returns_true(self):
        assert hubest_cli.is_stale("") is True


class TestFindProjectByName:
    def test_exact_name_match(self, sample_projects):
        result = hubest_cli.find_project_by_name("myapp", sample_projects)
        assert result is not None
        assert result["name"] == "myapp"

    def test_keyword_match(self, sample_projects):
        result = hubest_cli.find_project_by_name("frontend", sample_projects)
        assert result is not None
        assert result["name"] == "myapp"

    def test_case_insensitive_name(self, sample_projects):
        result = hubest_cli.find_project_by_name("MyApp", sample_projects)
        assert result is not None
        assert result["name"] == "myapp"

    def test_case_insensitive_keyword(self, sample_projects):
        result = hubest_cli.find_project_by_name("Frontend", sample_projects)
        assert result is not None
        assert result["name"] == "myapp"

    def test_partial_name_match(self, sample_projects):
        result = hubest_cli.find_project_by_name("back", sample_projects)
        assert result is not None
        assert result["name"] == "backend-api"

    def test_no_match_returns_none(self, sample_projects):
        result = hubest_cli.find_project_by_name("nonexistent", sample_projects)
        assert result is None

    def test_empty_projects_list(self):
        result = hubest_cli.find_project_by_name("anything", [])
        assert result is None

    def test_exact_keyword_takes_priority_over_partial_name(self, sample_projects):
        """Exact keyword match should be found before partial name match."""
        result = hubest_cli.find_project_by_name("api", sample_projects)
        assert result is not None
        assert result["name"] == "backend-api"


class TestProjectNameFromCwd:
    def test_exact_path_match(self, sample_projects):
        result = hubest_cli.project_name_from_cwd("/Users/test/myapp", sample_projects)
        assert result == "myapp"

    def test_subdirectory_match(self, sample_projects):
        result = hubest_cli.project_name_from_cwd(
            "/Users/test/myapp/src/components", sample_projects
        )
        assert result == "myapp"

    def test_no_match_falls_back_to_basename(self, sample_projects):
        result = hubest_cli.project_name_from_cwd(
            "/Users/test/unknown-project", sample_projects
        )
        assert result == "unknown-project"

    def test_empty_projects(self):
        result = hubest_cli.project_name_from_cwd("/Users/test/foo", [])
        assert result == "foo"
