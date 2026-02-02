"""Tests for CLI: _preprocess_argv, build_parser, resolve_session, cmd_view, cmd_copy."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import cchat
from cchat import (
    _preprocess_argv,
    build_parser,
    resolve_session,
    cmd_view,
    Session,
)


# ── _preprocess_argv ──────────────────────────────────────────────────────

class TestPreprocessArgv:
    def test_normal_unchanged(self):
        argv = ["view", "-n", "5"]
        assert _preprocess_argv(argv) == ["view", "-n", "5"]

    def test_negative_range_merged(self):
        argv = ["view", "-r", "-3--1"]
        assert _preprocess_argv(argv) == ["view", "-r=-3--1"]

    def test_positive_range_merged(self):
        argv = ["view", "-r", "3-5"]
        assert _preprocess_argv(argv) == ["view", "-r=3-5"]

    def test_single_negative_merged(self):
        argv = ["view", "-r", "-1"]
        assert _preprocess_argv(argv) == ["view", "-r=-1"]

    def test_r_at_end(self):
        # -r with no following argument should be unchanged
        argv = ["view", "-r"]
        assert _preprocess_argv(argv) == ["view", "-r"]

    def test_r_with_non_range(self):
        # -r followed by something that isn't a range
        argv = ["view", "-r", "--json"]
        assert _preprocess_argv(argv) == ["view", "-r", "--json"]

    def test_multiple_flags(self):
        argv = ["view", "-n", "3", "-r", "1-5", "--tools"]
        assert _preprocess_argv(argv) == ["view", "-n", "3", "-r=1-5", "--tools"]


# ── build_parser ──────────────────────────────────────────────────────────

class TestBuildParser:
    def test_list_defaults(self):
        parser = build_parser()
        args = parser.parse_args(["list"])
        assert args.command == "list"
        assert args.count == 10

    def test_view_defaults(self):
        parser = build_parser()
        args = parser.parse_args(["view"])
        assert args.command == "view"
        assert args.session is None
        assert args.n is None
        assert args.all is False
        assert args.tools is False
        assert args.raw is False
        assert args.json is False
        assert args.branch == 0

    def test_view_with_flags(self):
        parser = build_parser()
        args = parser.parse_args(["view", "abc123", "-n", "3", "--tools", "--json", "--timestamps"])
        assert args.session == "abc123"
        assert args.n == 3
        assert args.tools is True
        assert args.json is True
        assert args.timestamps is True

    def test_copy_defaults(self):
        parser = build_parser()
        args = parser.parse_args(["copy"])
        assert args.command == "copy"

    def test_search_pattern(self):
        parser = build_parser()
        args = parser.parse_args(["search", "hello"])
        assert args.pattern == "hello"
        assert args.limit == 20

    def test_tree_command(self):
        parser = build_parser()
        args = parser.parse_args(["tree"])
        assert args.command == "tree"
        assert args.branch == 0

    def test_export_defaults(self):
        parser = build_parser()
        args = parser.parse_args(["export"])
        assert args.command == "export"
        assert args.json is False
        assert args.raw is False

    def test_alias_ls(self):
        parser = build_parser()
        args = parser.parse_args(["ls"])
        assert args.command == "ls"

    def test_alias_v(self):
        parser = build_parser()
        args = parser.parse_args(["v"])
        assert args.command == "v"

    def test_alias_cp(self):
        parser = build_parser()
        args = parser.parse_args(["cp"])
        assert args.command == "cp"

    def test_alias_s(self):
        parser = build_parser()
        args = parser.parse_args(["s", "pattern"])
        assert args.command == "s"

    def test_project_flag(self):
        parser = build_parser()
        args = parser.parse_args(["view", "-p", "/some/path"])
        assert args.project == "/some/path"


# ── resolve_session ───────────────────────────────────────────────────────

class TestResolveSession:
    def test_latest_when_none(self, mock_project_dir):
        import time
        # Make sess-tool newer
        tool = mock_project_dir / "sess-tool.jsonl"
        time.sleep(0.05)
        tool.write_text(tool.read_text())

        result = resolve_session(mock_project_dir, None)
        assert result.name == "sess-tool.jsonl"

    def test_numeric_index(self, mock_project_dir):
        result = resolve_session(mock_project_dir, "1")
        assert result.suffix == ".jsonl"

    def test_uuid_prefix(self, mock_project_dir):
        result = resolve_session(mock_project_dir, "sess-simple")
        assert result.name == "sess-simple.jsonl"

    def test_not_found_exits(self, mock_project_dir):
        with pytest.raises(SystemExit):
            resolve_session(mock_project_dir, "nonexistent-uuid-xyz")

    def test_out_of_range_exits(self, mock_project_dir):
        with pytest.raises(SystemExit):
            resolve_session(mock_project_dir, "999")

    def test_no_sessions_exits(self, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        with pytest.raises(SystemExit):
            resolve_session(empty_dir, None)


# ── cmd_view ──────────────────────────────────────────────────────────────

class TestCmdView:
    def _make_args(self, **kwargs):
        """Create a namespace mimicking parsed args."""
        import argparse
        defaults = {
            "project": None,
            "session": None,
            "n": None,
            "r": None,
            "all": True,
            "tools": False,
            "raw": False,
            "json": False,
            "no_stitch": False,
            "timestamps": False,
            "compact_summaries": False,
            "truncate": 500,
            "branch": 0,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    def test_simple_session_output(self, mock_project_dir, capsys, monkeypatch):
        monkeypatch.setattr(cchat, "PROJECTS_DIR", mock_project_dir.parent)

        # Monkeypatch get_project_dir_or_exit to return our mock dir
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: mock_project_dir)
        )

        args = self._make_args()
        cmd_view(args)
        captured = capsys.readouterr()
        assert "USER" in captured.out
        assert "ASSISTANT" in captured.out

    def test_json_output_parseable(self, mock_project_dir, capsys, monkeypatch):
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: mock_project_dir)
        )

        args = self._make_args(json=True)
        cmd_view(args)
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "session_id" in data
        assert "turns" in data


# ── cmd_copy ──────────────────────────────────────────────────────────────

class TestCmdCopy:
    def _make_args(self, **kwargs):
        import argparse
        defaults = {
            "project": None,
            "session": None,
            "n": None,
            "r": "-1",
            "tools": False,
            "raw": False,
            "branch": 0,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    def test_copy_captures_text(self, mock_project_dir, monkeypatch):
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: mock_project_dir)
        )

        captured_text = []

        def fake_copy(text):
            captured_text.append(text)
            return True

        monkeypatch.setattr(cchat, "copy_to_clipboard", fake_copy)

        args = self._make_args()
        cchat.cmd_copy(args)
        assert len(captured_text) == 1
        assert len(captured_text[0]) > 0
