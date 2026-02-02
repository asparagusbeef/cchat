"""Tests for CLI: _preprocess_argv, build_parser, resolve_session, cmd_*, main."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
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

    def test_copy_raw_mode(self, mock_project_dir, monkeypatch):
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: mock_project_dir)
        )
        captured_text = []
        monkeypatch.setattr(cchat, "copy_to_clipboard", lambda t: (captured_text.append(t), True)[-1])

        # Use r=None, n=None so the default "-1" logic in cmd_copy is exercised
        args = self._make_args(raw=True, r=None, n=None)
        cchat.cmd_copy(args)
        assert len(captured_text) == 1

    def test_copy_multiple_turns(self, mock_project_dir, capsys, monkeypatch):
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: mock_project_dir)
        )
        monkeypatch.setattr(cchat, "copy_to_clipboard", lambda t: True)

        args = self._make_args(r="1-3", n=None)
        cchat.cmd_copy(args)
        captured = capsys.readouterr()
        assert "Copied" in captured.out

    def test_copy_clipboard_failure_exits(self, mock_project_dir, monkeypatch):
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: mock_project_dir)
        )
        monkeypatch.setattr(cchat, "copy_to_clipboard", lambda t: False)

        args = self._make_args()
        with pytest.raises(SystemExit):
            cchat.cmd_copy(args)

    def test_copy_empty_session_exits(self, tmp_path, monkeypatch):
        proj = tmp_path / "proj"
        proj.mkdir()
        p = proj / "empty.jsonl"
        p.write_text("")
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: proj)
        )
        args = self._make_args()
        with pytest.raises(SystemExit):
            cchat.cmd_copy(args)


# ── resolve_session (ambiguous) ──────────────────────────────────────────

class TestResolveSessionAmbiguous:
    def test_ambiguous_prefix_exits(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "abc-111.jsonl").write_text('{"type":"user","uuid":"u1","parentUuid":null,"message":{"role":"user","content":"Hi"}}\n')
        (proj / "abc-222.jsonl").write_text('{"type":"user","uuid":"u2","parentUuid":null,"message":{"role":"user","content":"Hi"}}\n')
        with pytest.raises(SystemExit):
            resolve_session(proj, "abc")


# ── cmd_list ──────────────────────────────────────────────────────────────

class TestCmdList:
    def _make_args(self, **kwargs):
        defaults = {"project": None, "count": 10}
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    def test_list_sessions(self, mock_project_dir, capsys, monkeypatch):
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: mock_project_dir)
        )
        cchat.cmd_list(self._make_args())
        captured = capsys.readouterr()
        assert "Sessions in" in captured.out
        assert "turn" in captured.out

    def test_list_no_sessions(self, tmp_path, capsys, monkeypatch):
        empty = tmp_path / "empty"
        empty.mkdir()
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: empty)
        )
        cchat.cmd_list(self._make_args())
        captured = capsys.readouterr()
        assert "No sessions" in captured.out

    def test_list_with_count(self, mock_project_dir, capsys, monkeypatch):
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: mock_project_dir)
        )
        cchat.cmd_list(self._make_args(count=1))
        captured = capsys.readouterr()
        # Should list at most 1 session
        assert "Sessions in" in captured.out


# ── cmd_view extended ────────────────────────────────────────────────────

class TestCmdViewRaw:
    def _make_args(self, **kwargs):
        defaults = {
            "project": None, "session": None, "n": None, "r": None,
            "all": True, "tools": False, "raw": True, "json": False,
            "no_stitch": False, "timestamps": False,
            "compact_summaries": False, "truncate": 500, "branch": 0,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    def test_raw_mode_output(self, mock_project_dir, capsys, monkeypatch):
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: mock_project_dir)
        )
        cchat.cmd_view(self._make_args())
        captured = capsys.readouterr()
        assert "raw messages" in captured.out

    def test_raw_json_output(self, mock_project_dir, capsys, monkeypatch):
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: mock_project_dir)
        )
        cchat.cmd_view(self._make_args(json=True))
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "messages" in data

    def test_raw_no_matching_range_exits(self, mock_project_dir, monkeypatch):
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: mock_project_dir)
        )
        with pytest.raises(SystemExit):
            cchat.cmd_view(self._make_args(all=False, r="999"))


class TestCmdViewEdgeCases:
    def _make_args(self, **kwargs):
        defaults = {
            "project": None, "session": None, "n": None, "r": None,
            "all": True, "tools": False, "raw": False, "json": False,
            "no_stitch": False, "timestamps": False,
            "compact_summaries": False, "truncate": 500, "branch": 0,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    def test_empty_session(self, tmp_path, capsys, monkeypatch):
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "empty.jsonl").write_text("")
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: proj)
        )
        cchat.cmd_view(self._make_args())
        captured = capsys.readouterr()
        assert "No messages" in captured.out

    def test_no_turns_session(self, tmp_path, capsys, monkeypatch):
        """Session with only system entries has no turns."""
        proj = tmp_path / "proj"
        proj.mkdir()
        line = json.dumps({"type": "system", "uuid": "s1", "parentUuid": None,
                           "subtype": "init"})
        (proj / "sys.jsonl").write_text(line + "\n")
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: proj)
        )
        cchat.cmd_view(self._make_args())
        captured = capsys.readouterr()
        assert "No conversation turns" in captured.out

    def test_no_matching_turns_exits(self, mock_project_dir, monkeypatch):
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: mock_project_dir)
        )
        with pytest.raises(SystemExit):
            cchat.cmd_view(self._make_args(all=False, r="999"))

    def test_view_with_tools(self, mock_project_dir_full, capsys, monkeypatch):
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: mock_project_dir_full)
        )
        args = self._make_args(session="sess-tool-session", tools=True)
        cchat.cmd_view(args)
        captured = capsys.readouterr()
        assert "USER" in captured.out

    def test_view_with_timestamps(self, mock_project_dir, capsys, monkeypatch):
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: mock_project_dir)
        )
        args = self._make_args(timestamps=True)
        cchat.cmd_view(args)
        captured = capsys.readouterr()
        assert "USER" in captured.out


# ── cmd_search ───────────────────────────────────────────────────────────

class TestCmdSearch:
    def _make_args(self, **kwargs):
        defaults = {"project": None, "pattern": "Hello", "limit": 20}
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    def test_search_finds_match(self, mock_project_dir, capsys, monkeypatch):
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: mock_project_dir)
        )
        cchat.cmd_search(self._make_args(pattern="Hello"))
        captured = capsys.readouterr()
        assert "Found" in captured.out
        assert "Hello" in captured.out

    def test_search_no_match(self, mock_project_dir, capsys, monkeypatch):
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: mock_project_dir)
        )
        cchat.cmd_search(self._make_args(pattern="ZZZZNONEXISTENTZZZZ"))
        captured = capsys.readouterr()
        assert "No matches" in captured.out

    def test_search_no_sessions(self, tmp_path, capsys, monkeypatch):
        empty = tmp_path / "empty"
        empty.mkdir()
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: empty)
        )
        cchat.cmd_search(self._make_args())
        captured = capsys.readouterr()
        assert "No sessions" in captured.out

    def test_search_respects_limit(self, mock_project_dir, capsys, monkeypatch):
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: mock_project_dir)
        )
        cchat.cmd_search(self._make_args(pattern="the", limit=1))
        captured = capsys.readouterr()
        # Should find at most 1 result
        assert "Found 1 match" in captured.out

    def test_search_case_insensitive(self, mock_project_dir, capsys, monkeypatch):
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: mock_project_dir)
        )
        cchat.cmd_search(self._make_args(pattern="hello"))
        captured = capsys.readouterr()
        assert "Found" in captured.out


# ── cmd_tree ─────────────────────────────────────────────────────────────

class TestCmdTree:
    def _make_args(self, **kwargs):
        defaults = {"project": None, "session": None, "branch": 0}
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    def test_tree_simple(self, mock_project_dir, capsys, monkeypatch):
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: mock_project_dir)
        )
        cchat.cmd_tree(self._make_args())
        captured = capsys.readouterr()
        assert "Session:" in captured.out
        assert "turn" in captured.out.lower()

    def test_tree_with_branches(self, mock_project_dir_full, capsys, monkeypatch):
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: mock_project_dir_full)
        )
        cchat.cmd_tree(self._make_args(session="sess-branched-session"))
        captured = capsys.readouterr()
        assert "Session:" in captured.out
        assert "branch" in captured.out.lower() or "Branch" in captured.out

    def test_tree_empty_session(self, tmp_path, capsys, monkeypatch):
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "empty.jsonl").write_text("")
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: proj)
        )
        cchat.cmd_tree(self._make_args())
        captured = capsys.readouterr()
        assert "No messages" in captured.out

    def test_tree_specific_branch(self, mock_project_dir_full, capsys, monkeypatch):
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: mock_project_dir_full)
        )
        cchat.cmd_tree(self._make_args(session="sess-branched-session", branch=1))
        captured = capsys.readouterr()
        assert "Branch 1" in captured.out


# ── cmd_export ───────────────────────────────────────────────────────────

class TestCmdExport:
    def _make_args(self, **kwargs):
        defaults = {
            "project": None, "session": None, "json": False,
            "raw": False, "include_tools": False, "branch": 0,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    def test_export_markdown(self, mock_project_dir, capsys, monkeypatch):
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: mock_project_dir)
        )
        cchat.cmd_export(self._make_args())
        captured = capsys.readouterr()
        assert "# Session" in captured.out
        assert "Turns:" in captured.out

    def test_export_json(self, mock_project_dir, capsys, monkeypatch):
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: mock_project_dir)
        )
        cchat.cmd_export(self._make_args(json=True))
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "session_id" in data
        assert "turns" in data

    def test_export_raw_json(self, mock_project_dir, capsys, monkeypatch):
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: mock_project_dir)
        )
        cchat.cmd_export(self._make_args(json=True, raw=True))
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "messages" in data

    def test_export_with_tools(self, mock_project_dir_full, capsys, monkeypatch):
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: mock_project_dir_full)
        )
        cchat.cmd_export(self._make_args(session="sess-tool-session", include_tools=True))
        captured = capsys.readouterr()
        assert "# Session" in captured.out

    def test_export_empty_session(self, tmp_path, capsys, monkeypatch):
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "empty.jsonl").write_text("")
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: proj)
        )
        cchat.cmd_export(self._make_args())
        captured = capsys.readouterr()
        assert "No messages" in captured.out


# ── cmd_projects ─────────────────────────────────────────────────────────

class TestCmdProjects:
    def test_list_projects(self, mock_claude_dir, capsys):
        _, projects_dir = mock_claude_dir
        proj = projects_dir / "-home-test"
        proj.mkdir()
        (proj / "session1.jsonl").write_text('{"type":"user"}\n')

        cchat.cmd_projects(argparse.Namespace())
        captured = capsys.readouterr()
        assert "Projects" in captured.out
        assert "1 session" in captured.out

    def test_no_projects(self, mock_claude_dir, capsys):
        cchat.cmd_projects(argparse.Namespace())
        captured = capsys.readouterr()
        assert "No projects" in captured.out


# ── main ─────────────────────────────────────────────────────────────────

class TestMain:
    def test_no_command_shows_help(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["cchat"])
        with pytest.raises(SystemExit) as exc:
            cchat.main()
        assert exc.value.code == 0

    def test_list_command_via_main(self, mock_project_dir, capsys, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["cchat", "list"])
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: mock_project_dir)
        )
        cchat.main()
        captured = capsys.readouterr()
        assert "Sessions" in captured.out or "No sessions" in captured.out

    def test_view_alias_via_main(self, mock_project_dir, capsys, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["cchat", "v", "--all"])
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: mock_project_dir)
        )
        cchat.main()
        captured = capsys.readouterr()
        assert "USER" in captured.out


# ── cmd_list with branches ───────────────────────────────────────────────

class TestCmdListLongSummary:
    def test_list_truncates_long_summary(self, tmp_path, capsys, monkeypatch):
        """cmd_list should truncate summary longer than 76 chars."""
        proj = tmp_path / "proj"
        proj.mkdir()
        long_summary = "A" * 100
        lines = [
            json.dumps({"type": "summary", "summary": long_summary}),
            json.dumps({"type": "user", "uuid": "u1", "parentUuid": None,
                         "message": {"role": "user", "content": "Hello"}}),
            json.dumps({"type": "assistant", "uuid": "u2", "parentUuid": "u1",
                         "message": {"role": "assistant",
                                     "content": [{"type": "text", "text": "Hi"}]}}),
        ]
        (proj / "long.jsonl").write_text("\n".join(lines) + "\n")
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: proj)
        )
        cchat.cmd_list(argparse.Namespace(project=None, count=10))
        captured = capsys.readouterr()
        assert "..." in captured.out


class TestCmdListModifiedFallback:
    def test_list_with_unparseable_modified_timestamp(self, tmp_path, capsys, monkeypatch):
        """When modified timestamp is not ISO parseable, fallback to string slice."""
        proj = tmp_path / "proj"
        proj.mkdir()
        # Use sessions-index.json with a garbage modified string
        index_data = {
            "version": 1,
            "entries": [{
                "sessionId": "test-sess",
                "summary": "Test",
                "firstPrompt": "Hello",
                "messageCount": 2,
                "created": "not-a-date",
                "modified": "not-a-date-either",
            }]
        }
        (proj / "sessions-index.json").write_text(json.dumps(index_data))
        lines = [
            json.dumps({"type": "user", "uuid": "u1", "parentUuid": None,
                         "message": {"role": "user", "content": "Hello"}}),
            json.dumps({"type": "assistant", "uuid": "u2", "parentUuid": "u1",
                         "message": {"role": "assistant",
                                     "content": [{"type": "text", "text": "Hi"}]}}),
        ]
        (proj / "test-sess.jsonl").write_text("\n".join(lines) + "\n")
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: proj)
        )
        cchat.cmd_list(argparse.Namespace(project=None, count=10))
        captured = capsys.readouterr()
        assert "not-a-date-eithe" in captured.out  # first 16 chars


class TestCmdListCorruptSession:
    def test_list_handles_corrupt_session(self, tmp_path, capsys, monkeypatch):
        """cmd_list should not crash on a corrupt session file."""
        proj = tmp_path / "proj"
        proj.mkdir()
        # Create a valid session file
        lines = [
            json.dumps({"type": "summary", "summary": "Valid"}),
            json.dumps({"type": "user", "uuid": "u1", "parentUuid": None,
                         "message": {"role": "user", "content": "Hello"}}),
            json.dumps({"type": "assistant", "uuid": "u2", "parentUuid": "u1",
                         "message": {"role": "assistant",
                                     "content": [{"type": "text", "text": "Hi"}]}}),
        ]
        (proj / "valid.jsonl").write_text("\n".join(lines) + "\n")
        # Create a corrupt session file (invalid JSON)
        (proj / "corrupt.jsonl").write_text("{{{bad json\n")
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: proj)
        )
        cchat.cmd_list(argparse.Namespace(project=None, count=10))
        captured = capsys.readouterr()
        assert "Sessions in" in captured.out


class TestCmdListException:
    def test_list_handles_session_exception(self, tmp_path, capsys, monkeypatch):
        """cmd_list should catch exceptions during session loading and continue."""
        proj = tmp_path / "proj"
        proj.mkdir()
        lines = [
            json.dumps({"type": "summary", "summary": "Test session"}),
            json.dumps({"type": "user", "uuid": "u1", "parentUuid": None,
                         "message": {"role": "user", "content": "Hello"}}),
        ]
        (proj / "test.jsonl").write_text("\n".join(lines) + "\n")
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: proj)
        )
        # Monkeypatch Session.active_path to raise
        original = cchat.Session.active_path
        monkeypatch.setattr(cchat.Session, "active_path",
                            lambda self, **kw: (_ for _ in ()).throw(RuntimeError("test")))
        cchat.cmd_list(argparse.Namespace(project=None, count=10))
        captured = capsys.readouterr()
        # Should still list the session with fallback msg_info
        assert "msgs" in captured.out


class TestCmdListBranched:
    def test_list_shows_branch_info(self, mock_project_dir_full, capsys, monkeypatch):
        """cmd_list should show branch point count for sessions with branches."""
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: mock_project_dir_full)
        )
        cchat.cmd_list(argparse.Namespace(project=None, count=10))
        captured = capsys.readouterr()
        assert "branch pt" in captured.out


# ── cmd_search snippet context ───────────────────────────────────────────

class TestCmdSearchSnippet:
    def test_search_snippet_with_ellipsis(self, tmp_path, capsys, monkeypatch):
        """Search match in middle of long text should have ... context."""
        proj = tmp_path / "proj"
        proj.mkdir()
        long_text = ("A" * 60) + "FINDME" + ("B" * 60)
        line = json.dumps({"type": "user", "uuid": "u1", "parentUuid": None,
                           "message": {"role": "user", "content": long_text}})
        (proj / "long.jsonl").write_text(line + "\n")
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: proj)
        )
        cchat.cmd_search(argparse.Namespace(project=None, pattern="FINDME", limit=20))
        captured = capsys.readouterr()
        assert "Found" in captured.out
        assert "..." in captured.out

    def test_search_skips_non_user_assistant_entries(self, tmp_path, capsys, monkeypatch):
        """Search should skip system/progress entries even if they match."""
        proj = tmp_path / "proj"
        proj.mkdir()
        lines = [
            json.dumps({"type": "system", "uuid": "s1", "parentUuid": None,
                         "subtype": "init", "message": {"content": "SEARCHME"}}),
            json.dumps({"type": "user", "uuid": "u1", "parentUuid": None,
                         "message": {"role": "user", "content": "SEARCHME user"}}),
        ]
        (proj / "mixed.jsonl").write_text("\n".join(lines) + "\n")
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: proj)
        )
        cchat.cmd_search(argparse.Namespace(project=None, pattern="SEARCHME", limit=20))
        captured = capsys.readouterr()
        assert "Found 1 match" in captured.out
        assert "user" in captured.out

    def test_search_match_in_assistant_text_block(self, tmp_path, capsys, monkeypatch):
        """Search should find matches in assistant text blocks."""
        proj = tmp_path / "proj"
        proj.mkdir()
        line = json.dumps({"type": "assistant", "uuid": "u1", "parentUuid": None,
                           "message": {"role": "assistant",
                                       "content": [{"type": "text", "text": "The answer is 42"}]}})
        (proj / "asst.jsonl").write_text(line + "\n")
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: proj)
        )
        cchat.cmd_search(argparse.Namespace(project=None, pattern="answer is 42", limit=20))
        captured = capsys.readouterr()
        assert "Found" in captured.out


# ── cmd_tree with long text ──────────────────────────────────────────────

class TestCmdTreeLongText:
    def test_tree_truncates_long_text(self, tmp_path, capsys, monkeypatch):
        """Tree should truncate user/assistant text longer than 60 chars."""
        proj = tmp_path / "proj"
        proj.mkdir()
        long_user = "X" * 80
        long_asst = "Y" * 80
        lines = [
            json.dumps({"type": "user", "uuid": "u1", "parentUuid": None,
                         "message": {"role": "user", "content": long_user}}),
            json.dumps({"type": "assistant", "uuid": "u2", "parentUuid": "u1",
                         "message": {"role": "assistant",
                                     "content": [{"type": "text", "text": long_asst}]}}),
        ]
        (proj / "long.jsonl").write_text("\n".join(lines) + "\n")
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: proj)
        )
        cchat.cmd_tree(argparse.Namespace(project=None, session=None, branch=0))
        captured = capsys.readouterr()
        assert "..." in captured.out


# ── cmd_export markdown no turns ─────────────────────────────────────────

class TestCmdExportNoTurns:
    def test_export_markdown_no_turns(self, tmp_path, capsys, monkeypatch):
        """Markdown export with entries but no turns shows 'No conversation turns.'"""
        proj = tmp_path / "proj"
        proj.mkdir()
        line = json.dumps({"type": "system", "uuid": "s1", "parentUuid": None,
                           "subtype": "init"})
        (proj / "sys.jsonl").write_text(line + "\n")
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: proj)
        )
        args = argparse.Namespace(project=None, session=None, json=False,
                                  raw=False, include_tools=False, branch=0)
        cchat.cmd_export(args)
        captured = capsys.readouterr()
        assert "No conversation turns" in captured.out or "No messages" in captured.out


# ── cmd_copy no matching turns ───────────────────────────────────────────

class TestCmdCopyCompactFallback:
    def test_copy_compact_summaries_fallback(self, tmp_path, capsys, monkeypatch):
        """cmd_copy falls back to include compact summaries when turns are empty."""
        proj = tmp_path / "proj"
        proj.mkdir()
        lines = [
            json.dumps({"type": "system", "uuid": "cb1", "parentUuid": None,
                         "subtype": "compact_boundary",
                         "logicalParentUuid": "old-uuid"}),
            json.dumps({"type": "user", "uuid": "u1", "parentUuid": "cb1",
                         "isCompactSummary": True,
                         "isVisibleInTranscriptOnly": True,
                         "message": {"role": "user", "content": "[Summary of conversation]"}}),
            json.dumps({"type": "assistant", "uuid": "u2", "parentUuid": "u1",
                         "message": {"role": "assistant",
                                     "content": [{"type": "text", "text": "Continuing"}]}}),
        ]
        (proj / "compact.jsonl").write_text("\n".join(lines) + "\n")
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: proj)
        )
        captured = []
        monkeypatch.setattr(cchat, "copy_to_clipboard", lambda t: (captured.append(t), True)[-1])
        args = argparse.Namespace(project=None, session=None, n=None,
                                  r=None, tools=False, raw=False, branch=0)
        cchat.cmd_copy(args)
        assert len(captured) == 1
        assert "Summary" in captured[0] or "Continuing" in captured[0]


class TestCmdCopyDefaults:
    def test_copy_turn_mode_default_r(self, mock_project_dir, monkeypatch):
        """When r=None and n=None in turn mode, cmd_copy defaults to r='-1'."""
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: mock_project_dir)
        )
        captured = []
        monkeypatch.setattr(cchat, "copy_to_clipboard", lambda t: (captured.append(t), True)[-1])
        args = argparse.Namespace(project=None, session=None, n=None,
                                  r=None, tools=False, raw=False, branch=0)
        cchat.cmd_copy(args)
        assert len(captured) == 1


class TestCmdCopyNoMatch:
    def test_copy_no_matching_turns_exits(self, mock_project_dir, monkeypatch):
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: mock_project_dir)
        )
        monkeypatch.setattr(cchat, "copy_to_clipboard", lambda t: True)
        args = argparse.Namespace(project=None, session=None, n=None,
                                  r="999", tools=False, raw=False, branch=0)
        with pytest.raises(SystemExit):
            cchat.cmd_copy(args)

    def test_copy_raw_no_matching_exits(self, mock_project_dir, monkeypatch):
        monkeypatch.setattr(
            cchat.ProjectResolver, "get_project_dir_or_exit",
            staticmethod(lambda project_override=None: mock_project_dir)
        )
        monkeypatch.setattr(cchat, "copy_to_clipboard", lambda t: True)
        args = argparse.Namespace(project=None, session=None, n=None,
                                  r="999", tools=False, raw=True, branch=0)
        with pytest.raises(SystemExit):
            cchat.cmd_copy(args)
