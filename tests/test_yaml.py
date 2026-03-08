"""Tests for YAML utilities in hubest_cli."""

import os

import hubest_cli


class TestSimpleYamlLoad:
    def test_parse_valid_content(self, tmp_path):
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text(
            "projects:\n"
            '  - name: myapp\n'
            '    path: /Users/test/myapp\n'
            '    keywords: ["app", "frontend"]\n'
        )
        data = hubest_cli._simple_yaml_load(str(yaml_file))
        assert "projects" in data
        assert len(data["projects"]) == 1
        assert data["projects"][0]["name"] == "myapp"
        assert data["projects"][0]["path"] == "/Users/test/myapp"

    def test_parse_keywords_list(self, tmp_path):
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text(
            "projects:\n"
            '  - name: myapp\n'
            '    path: /path\n'
            '    keywords: ["kw1", "kw2", "kw3"]\n'
        )
        data = hubest_cli._simple_yaml_load(str(yaml_file))
        kws = data["projects"][0]["keywords"]
        assert kws == ["kw1", "kw2", "kw3"]

    def test_nonexistent_file_returns_empty(self, tmp_path):
        data = hubest_cli._simple_yaml_load(str(tmp_path / "missing.yaml"))
        assert data == {}

    def test_multiple_projects(self, tmp_path):
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text(
            "projects:\n"
            '  - name: proj1\n'
            '    path: /path1\n'
            '    keywords: ["a"]\n'
            '  - name: proj2\n'
            '    path: /path2\n'
            '    keywords: ["b", "c"]\n'
        )
        data = hubest_cli._simple_yaml_load(str(yaml_file))
        assert len(data["projects"]) == 2
        assert data["projects"][0]["name"] == "proj1"
        assert data["projects"][1]["name"] == "proj2"

    def test_empty_keywords(self, tmp_path):
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text(
            "projects:\n"
            '  - name: proj\n'
            '    path: /path\n'
            '    keywords: []\n'
        )
        data = hubest_cli._simple_yaml_load(str(yaml_file))
        assert data["projects"][0]["keywords"] == []


class TestSimpleYamlSave:
    def test_save_single_project(self, tmp_path):
        yaml_file = tmp_path / "out.yaml"
        data = {
            "projects": [
                {"name": "myapp", "path": "/Users/test/myapp", "keywords": ["app"]}
            ]
        }
        hubest_cli._simple_yaml_save(str(yaml_file), data)
        content = yaml_file.read_text()
        assert "myapp" in content
        assert "/Users/test/myapp" in content
        assert '"app"' in content

    def test_save_multiple_projects(self, tmp_path):
        yaml_file = tmp_path / "out.yaml"
        data = {
            "projects": [
                {"name": "p1", "path": "/p1", "keywords": ["a"]},
                {"name": "p2", "path": "/p2", "keywords": ["b", "c"]},
            ]
        }
        hubest_cli._simple_yaml_save(str(yaml_file), data)
        content = yaml_file.read_text()
        assert "p1" in content
        assert "p2" in content

    def test_save_empty_projects(self, tmp_path):
        yaml_file = tmp_path / "out.yaml"
        hubest_cli._simple_yaml_save(str(yaml_file), {"projects": []})
        content = yaml_file.read_text()
        assert "projects:" in content


class TestYamlRoundTrip:
    def test_save_then_load_preserves_data(self, tmp_path):
        yaml_file = tmp_path / "roundtrip.yaml"
        original = {
            "projects": [
                {"name": "alpha", "path": "/alpha", "keywords": ["a", "alpha"]},
                {"name": "beta", "path": "/beta", "keywords": ["b"]},
            ]
        }
        hubest_cli._simple_yaml_save(str(yaml_file), original)
        loaded = hubest_cli._simple_yaml_load(str(yaml_file))

        assert len(loaded["projects"]) == 2
        assert loaded["projects"][0]["name"] == "alpha"
        assert loaded["projects"][0]["path"] == "/alpha"
        assert loaded["projects"][0]["keywords"] == ["a", "alpha"]
        assert loaded["projects"][1]["name"] == "beta"
        assert loaded["projects"][1]["keywords"] == ["b"]


class TestLoadSaveProjects:
    def test_load_empty_when_no_file(self, mock_hubest_paths):
        projects = hubest_cli.load_projects()
        assert projects == []

    def test_save_then_load(self, mock_hubest_paths):
        projects = [
            {"name": "test", "path": "/test", "keywords": ["t"]},
        ]
        hubest_cli.save_projects(projects)
        loaded = hubest_cli.load_projects()
        assert len(loaded) == 1
        assert loaded[0]["name"] == "test"
        assert loaded[0]["path"] == "/test"

    def test_save_empty_list(self, mock_hubest_paths):
        hubest_cli.save_projects([])
        loaded = hubest_cli.load_projects()
        assert loaded == []
