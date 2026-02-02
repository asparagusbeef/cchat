"""Tests for formatting functions: ToolSummary.one_line, format_turn, format_raw_message, JSON formatters."""

from __future__ import annotations

import json

import pytest

from cchat import (
    ToolSummary,
    Turn,
    RawMessage,
    format_turn,
    format_raw_message,
    format_turns_json,
    format_raw_json,
)


# ── ToolSummary.one_line ──────────────────────────────────────────────────

class TestToolSummaryOneLine:
    @pytest.mark.parametrize("name,inp,expected", [
        ("Read", {"file_path": "/home/user/file.py"}, "[Read] .../home/user/file.py"),
        ("Write", {"file_path": "/tmp/out.txt"}, "[Write] /tmp/out.txt"),
        ("Edit", {"file_path": "/a/b/c.py"}, "[Edit] .../a/b/c.py"),
        ("Bash", {"command": "ls -la", "description": "List files"}, "[Bash] List files"),
        ("Bash", {"command": "ls -la"}, "[Bash] ls -la"),
        ("Glob", {"pattern": "**/*.py"}, "[Glob] **/*.py"),
        ("Grep", {"pattern": "TODO"}, "[Grep] TODO"),
        ("WebFetch", {"url": "https://example.com"}, "[WebFetch] https://example.com"),
        ("WebSearch", {"query": "python async"}, "[WebSearch] python async"),
        ("Task", {"description": "run tests"}, "[Task] run tests"),
        ("TodoWrite", {}, "[TodoWrite]"),
        ("TaskCreate", {}, "[TaskCreate]"),
    ])
    def test_known_tools(self, name, inp, expected):
        ts = ToolSummary(name=name, input_data=inp)
        assert ts.one_line() == expected

    def test_unknown_tool(self):
        ts = ToolSummary(name="CustomTool", input_data={"key": "value"})
        result = ts.one_line()
        assert result.startswith("[CustomTool]")
        assert "key" in result

    def test_bash_long_command_no_description(self):
        long_cmd = "x" * 100
        ts = ToolSummary(name="Bash", input_data={"command": long_cmd})
        result = ts.one_line()
        assert result.startswith("[Bash] ")
        assert result.endswith("...")
        # 6 for "[Bash] " minus 1 + 60 + 3 for "..."
        assert len(result) <= 70

    def test_unknown_tool_long_input(self):
        ts = ToolSummary(name="X", input_data={"data": "a" * 100})
        result = ts.one_line()
        assert result.endswith("...")


# ── format_turn ───────────────────────────────────────────────────────────

class TestFormatTurn:
    def _make_turn(self, **kwargs):
        defaults = {
            "user_text": "Hello",
            "assistant_text": "Hi",
            "tool_calls": [],
            "timestamp": "2025-01-15T10:00:00Z",
            "uuid": "test-uuid",
            "is_compact_summary": False,
        }
        defaults.update(kwargs)
        return Turn(**defaults)

    def test_basic(self):
        turn = self._make_turn()
        result = format_turn(turn, 1, 3)
        assert "[1/3] USER" in result
        assert "Hello" in result
        assert "[1/3] ASSISTANT" in result
        assert "Hi" in result

    def test_with_timestamp(self):
        turn = self._make_turn()
        result = format_turn(turn, 1, 1, show_timestamp=True)
        assert "10:00:00" in result

    def test_compact_summary_label(self):
        turn = self._make_turn(is_compact_summary=True)
        result = format_turn(turn, 1, 1)
        assert "[Compaction Summary]" in result

    def test_with_tools(self):
        tools = [ToolSummary(name="Bash", input_data={"command": "ls"})]
        turn = self._make_turn(tool_calls=tools)
        result = format_turn(turn, 1, 1, show_tools=True)
        assert "[Bash] ls" in result
        assert "1 tool calls" in result

    def test_no_assistant_text(self):
        turn = self._make_turn(assistant_text="")
        result = format_turn(turn, 1, 1)
        assert "ASSISTANT" not in result


# ── format_raw_message ────────────────────────────────────────────────────

class TestFormatRawMessage:
    def _make_msg(self, **kwargs):
        defaults = {
            "role": "user",
            "content": "Hello world",
            "timestamp": "2025-01-15T10:00:00Z",
            "uuid": "test-uuid-1234",
            "entry_type": "user",
        }
        defaults.update(kwargs)
        return RawMessage(**defaults)

    def test_basic(self):
        msg = self._make_msg()
        result = format_raw_message(msg, 1, 5)
        assert "[1/5] USER" in result
        assert "Hello world" in result
        assert "test-uuid-12" in result  # uuid truncated to 12

    def test_with_timestamp(self):
        msg = self._make_msg()
        result = format_raw_message(msg, 1, 1, show_timestamp=True)
        assert "10:00:00" in result

    def test_ansi_stripped(self):
        msg = self._make_msg(content="\x1b[31mred text\x1b[0m")
        result = format_raw_message(msg, 1, 1)
        assert "red text" in result
        assert "\x1b" not in result


# ── JSON formatters ───────────────────────────────────────────────────────

class TestJsonFormatters:
    def test_format_turns_json_roundtrip(self):
        turns = [
            Turn(user_text="Q1", assistant_text="A1", tool_calls=[],
                 timestamp="2025-01-15T10:00:00Z", uuid="u1"),
            Turn(user_text="Q2", assistant_text="A2", tool_calls=[],
                 timestamp="2025-01-15T10:00:10Z", uuid="u2"),
        ]
        output = format_turns_json(turns, "test-session", 2, 1)
        data = json.loads(output)
        assert data["session_id"] == "test-session"
        assert data["total_turns"] == 2
        assert len(data["turns"]) == 2
        assert data["turns"][0]["user"]["text"] == "Q1"
        assert data["turns"][1]["assistant"]["text"] == "A2"

    def test_format_turns_json_with_tools(self):
        tools = [ToolSummary(name="Bash", input_data={"command": "ls"})]
        turns = [Turn(user_text="Do it", assistant_text="Done", tool_calls=tools,
                      timestamp="", uuid="u1")]
        output = format_turns_json(turns, "s1", 1, 1)
        data = json.loads(output)
        assert "tool_calls" in data["turns"][0]["assistant"]
        assert data["turns"][0]["assistant"]["tool_calls"][0]["name"] == "Bash"

    def test_format_raw_json_roundtrip(self):
        messages = [
            RawMessage(role="user", content="Hello", timestamp="", uuid="u1", entry_type="user"),
            RawMessage(role="assistant", content="Hi", timestamp="", uuid="u2", entry_type="assistant"),
        ]
        output = format_raw_json(messages, "test-session")
        data = json.loads(output)
        assert data["session_id"] == "test-session"
        assert data["total_messages"] == 2
        assert data["messages"][0]["role"] == "user"
        assert data["messages"][1]["content"] == "Hi"
