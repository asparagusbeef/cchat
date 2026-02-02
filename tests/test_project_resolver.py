"""Tests for ProjectResolver: get_project_key, find_project_dir, list_all_projects, get_project_dir_or_exit."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import cchat
from cchat import ProjectResolver


# ── get_project_key ───────────────────────────────────────────────────────

class TestGetProjectKey:
    def test_basic_path(self):
        key = ProjectResolver.get_project_key(Path("/home/user/project"))
        assert key == "-home-user-project"

    def test_root(self):
        key = ProjectResolver.get_project_key(Path("/"))
        assert key == "-"


# ── find_project_dir ──────────────────────────────────────────────────────

class TestFindProjectDir:
    def test_exact_match(self, mock_claude_dir):
        _, projects_dir = mock_claude_dir
        # Create a project directory
        proj = projects_dir / "-home-test"
        proj.mkdir()
        result = ProjectResolver.find_project_dir(Path("/home/test"))
        assert result == proj

    def test_case_insensitive(self, mock_claude_dir):
        _, projects_dir = mock_claude_dir
        proj = projects_dir / "-Home-Test"
        proj.mkdir()
        result = ProjectResolver.find_project_dir(Path("/home/test"))
        assert result == proj

    def test_no_match(self, mock_claude_dir):
        result = ProjectResolver.find_project_dir(Path("/nonexistent/path"))
        assert result is None

    def test_no_projects_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cchat, "PROJECTS_DIR", tmp_path / "nonexistent")
        result = ProjectResolver.find_project_dir(Path("/home/test"))
        assert result is None


# ── list_all_projects ─────────────────────────────────────────────────────

class TestListAllProjects:
    def test_projects_dir_not_exists(self, tmp_path, monkeypatch):
        """list_all_projects returns [] when PROJECTS_DIR doesn't exist."""
        monkeypatch.setattr(cchat, "PROJECTS_DIR", tmp_path / "nonexistent")
        assert ProjectResolver.list_all_projects() == []

    def test_skips_non_directory_entries(self, mock_claude_dir):
        """Non-directory files in PROJECTS_DIR should be skipped."""
        _, projects_dir = mock_claude_dir
        # Create a regular file (not dir) in PROJECTS_DIR
        (projects_dir / "stray-file.txt").write_text("not a directory")
        # Create a valid project dir
        proj = projects_dir / "-home-test"
        proj.mkdir()
        (proj / "s1.jsonl").write_text('{"type":"user"}\n')
        projects = ProjectResolver.list_all_projects()
        assert len(projects) == 1

    def test_empty(self, mock_claude_dir):
        projects = ProjectResolver.list_all_projects()
        assert projects == []

    def test_with_sessions(self, mock_claude_dir):
        _, projects_dir = mock_claude_dir
        proj = projects_dir / "-home-test"
        proj.mkdir()
        (proj / "session1.jsonl").write_text('{"type":"user"}\n')
        projects = ProjectResolver.list_all_projects()
        assert len(projects) == 1
        assert projects[0]["session_count"] == 1

    def test_skips_empty_dirs(self, mock_claude_dir):
        _, projects_dir = mock_claude_dir
        (projects_dir / "-empty-project").mkdir()
        projects = ProjectResolver.list_all_projects()
        assert len(projects) == 0

    def test_skips_agent_files(self, mock_claude_dir):
        _, projects_dir = mock_claude_dir
        proj = projects_dir / "-home-test"
        proj.mkdir()
        (proj / "agent-123.jsonl").write_text('{"type":"user"}\n')
        projects = ProjectResolver.list_all_projects()
        # Agent files don't count as sessions
        assert len(projects) == 0

    def test_multiple_projects_sorted_by_mtime(self, mock_claude_dir):
        _, projects_dir = mock_claude_dir
        import time

        proj1 = projects_dir / "-home-old"
        proj1.mkdir()
        (proj1 / "s1.jsonl").write_text('{"type":"user"}\n')

        time.sleep(0.05)

        proj2 = projects_dir / "-home-new"
        proj2.mkdir()
        (proj2 / "s2.jsonl").write_text('{"type":"user"}\n')

        projects = ProjectResolver.list_all_projects()
        assert len(projects) == 2
        # Most recent first
        assert projects[0]["name"] == "-home-new"


# ── get_project_dir_or_exit ───────────────────────────────────────────────

class TestGetProjectDirOrExit:
    def test_exit_on_not_found(self, mock_claude_dir, monkeypatch):
        # Use a cwd that has no project
        monkeypatch.chdir("/tmp")
        with pytest.raises(SystemExit):
            ProjectResolver.get_project_dir_or_exit()

    def test_project_override_works(self, mock_claude_dir):
        _, projects_dir = mock_claude_dir
        proj = projects_dir / "-home-test"
        proj.mkdir()
        (proj / "s.jsonl").write_text('{"type":"user"}\n')

        result = ProjectResolver.get_project_dir_or_exit("-home-test")
        assert result == proj

    def test_project_override_partial_match(self, mock_claude_dir):
        _, projects_dir = mock_claude_dir
        proj = projects_dir / "-home-test-project"
        proj.mkdir()
        (proj / "s.jsonl").write_text('{"type":"user"}\n')

        result = ProjectResolver.get_project_dir_or_exit("test-project")
        assert result == proj

    def test_project_override_via_path(self, mock_claude_dir):
        """Override with a real path that resolves to a project dir."""
        _, projects_dir = mock_claude_dir
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            project_key = ProjectResolver.get_project_key(Path(td))
            proj = projects_dir / project_key
            proj.mkdir()
            (proj / "s.jsonl").write_text('{"type":"user"}\n')
            result = ProjectResolver.get_project_dir_or_exit(td)
            assert result == proj

    def test_cwd_match_succeeds(self, mock_claude_dir, monkeypatch):
        """get_project_dir_or_exit succeeds when cwd matches a project."""
        _, projects_dir = mock_claude_dir
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            project_key = ProjectResolver.get_project_key(Path(td))
            proj = projects_dir / project_key
            proj.mkdir()
            (proj / "s.jsonl").write_text('{"type":"user"}\n')
            monkeypatch.chdir(td)
            result = ProjectResolver.get_project_dir_or_exit()
            assert result == proj

    def test_project_override_not_found_exits(self, mock_claude_dir):
        with pytest.raises(SystemExit):
            ProjectResolver.get_project_dir_or_exit("nonexistent-project-xyz")
