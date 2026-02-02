"""Tests for group_into_turns and extract_raw_messages."""

from __future__ import annotations

import pytest

from cchat import (
    Session,
    group_into_turns,
    extract_raw_messages,
)


# ── group_into_turns ──────────────────────────────────────────────────────

class TestGroupIntoTurns:
    def test_simple_three_turns(self, simple_session):
        path = simple_session.active_path()
        turns = group_into_turns(path, mode="text")
        assert len(turns) == 3

    def test_simple_turn_content(self, simple_session):
        path = simple_session.active_path()
        turns = group_into_turns(path, mode="text")
        assert turns[0].user_text == "Hello"
        assert turns[0].assistant_text == "Hi there"
        assert turns[1].user_text == "How are you?"
        assert turns[2].assistant_text == "See you later"

    def test_tool_mode_collects_tools(self, tool_session):
        path = tool_session.active_path()
        turns = group_into_turns(path, mode="tools")
        # First turn should have Bash tool call
        assert len(turns[0].tool_calls) >= 1
        assert turns[0].tool_calls[0].name == "Bash"

    def test_text_mode_no_tools(self, tool_session):
        path = tool_session.active_path()
        turns = group_into_turns(path, mode="text")
        for turn in turns:
            assert turn.tool_calls == []

    def test_tool_result_not_a_turn_start(self, tool_session):
        path = tool_session.active_path()
        turns = group_into_turns(path, mode="text")
        # tool_result entries should NOT create new turns
        # We should have 2 turns (user text messages), not more
        assert len(turns) == 2

    def test_excludes_compact_summaries_by_default(self, compacted_session):
        path = compacted_session.active_path()
        turns = group_into_turns(path, mode="text", include_compact_summaries=False)
        for turn in turns:
            assert not turn.is_compact_summary

    def test_includes_compact_summaries_when_requested(self, compacted_session):
        path = compacted_session.active_path()
        turns = group_into_turns(path, mode="text", include_compact_summaries=True)
        compact_turns = [t for t in turns if t.is_compact_summary]
        assert len(compact_turns) >= 1

    def test_skips_system_entries(self, compacted_session):
        path = compacted_session.active_path()
        turns = group_into_turns(path, mode="text")
        # System entries (compact_boundary) should not create turns
        for turn in turns:
            assert "Compaction boundary" not in turn.user_text

    def test_skips_progress_entries(self, tool_session):
        path = tool_session.active_path()
        turns = group_into_turns(path, mode="text")
        for turn in turns:
            assert turn.user_text != ""

    def test_assistant_text_concatenation(self, simple_session):
        """Assistant text from a single entry should be captured."""
        path = simple_session.active_path()
        turns = group_into_turns(path, mode="text")
        assert turns[1].assistant_text == "I am fine"

    def test_empty_path(self):
        turns = group_into_turns([], mode="text")
        assert turns == []

    def test_ansi_stripped_from_user_text(self, tmp_path):
        """ANSI codes in user text should be stripped."""
        import json
        lines = [
            json.dumps({"type": "user", "uuid": "u1", "parentUuid": None,
                         "message": {"role": "user", "content": "\x1b[31mRed prompt\x1b[0m"}}),
            json.dumps({"type": "assistant", "uuid": "u2", "parentUuid": "u1",
                         "message": {"role": "assistant",
                                     "content": [{"type": "text", "text": "Response"}]}}),
        ]
        p = tmp_path / "ansi.jsonl"
        p.write_text("\n".join(lines) + "\n")
        session = Session(p)
        turns = group_into_turns(session.active_path(), mode="text")
        assert turns[0].user_text == "Red prompt"

    def test_turn_timestamps(self, simple_session):
        path = simple_session.active_path()
        turns = group_into_turns(path, mode="text")
        assert turns[0].timestamp == "2025-01-15T10:00:00.000Z"

    def test_turn_uuids(self, simple_session):
        path = simple_session.active_path()
        turns = group_into_turns(path, mode="text")
        assert turns[0].uuid == "uuid-0001"
        assert turns[2].uuid == "uuid-0005"


# ── extract_raw_messages ──────────────────────────────────────────────────

class TestExtractRawMessages:
    def test_user_text_message(self, simple_session):
        path = simple_session.active_path()
        messages = extract_raw_messages(path)
        user_msgs = [m for m in messages if m.role == "user"]
        assert len(user_msgs) == 3
        assert user_msgs[0].content == "Hello"

    def test_tool_result_role(self, tool_session):
        path = tool_session.active_path()
        messages = extract_raw_messages(path)
        tool_result_msgs = [m for m in messages if m.role == "user (tool_result)"]
        assert len(tool_result_msgs) >= 1

    def test_tool_use_in_assistant(self, tool_session):
        path = tool_session.active_path()
        messages = extract_raw_messages(path)
        tool_msgs = [m for m in messages if m.role == "assistant (tool)"]
        assert len(tool_msgs) >= 1
        assert "Bash" in tool_msgs[0].content

    def test_compact_boundary_in_raw(self, compacted_session):
        path = compacted_session.active_path()
        messages = extract_raw_messages(path)
        boundary_msgs = [m for m in messages if "compact_boundary" in m.role]
        assert len(boundary_msgs) >= 1

    def test_truncation_on(self, tool_session):
        path = tool_session.active_path()
        messages = extract_raw_messages(path, truncate_len=5)
        # Some content should be truncated
        tool_results = [m for m in messages if "tool_result" in m.role]
        # tool result content "file1.txt\nfile2.txt" > 5 chars
        if tool_results:
            assert "..." in tool_results[0].content

    def test_truncation_off(self, tool_session):
        path = tool_session.active_path()
        messages = extract_raw_messages(path, truncate_len=-1)
        tool_results = [m for m in messages if "tool_result" in m.role]
        if tool_results:
            # Full content preserved
            assert "file1.txt" in tool_results[0].content

    def test_thinking_block(self, complex_session):
        path = complex_session.active_path()
        messages = extract_raw_messages(path)
        # The complex session has a thinking block in uuid-4002
        contents = " ".join(m.content for m in messages)
        assert "thinking" in contents.lower() or "think" in contents.lower()

    def test_progress_skipped(self, tool_session):
        path = tool_session.active_path()
        messages = extract_raw_messages(path)
        for m in messages:
            assert m.entry_type != "progress"

    def test_error_tool_result(self, tmp_path):
        """Tool result with is_error=True should show ERROR marker."""
        import json
        lines = [
            json.dumps({"type": "user", "uuid": "u1", "parentUuid": None,
                         "message": {"role": "user", "content": "Do something"}}),
            json.dumps({"type": "assistant", "uuid": "u2", "parentUuid": "u1",
                         "message": {"role": "assistant",
                                     "content": [{"type": "tool_use", "id": "t1",
                                                   "name": "Bash", "input": {"command": "fail"}}]},
                         "stopReason": "tool_use"}),
            json.dumps({"type": "user", "uuid": "u3", "parentUuid": "u2",
                         "message": {"role": "user",
                                     "content": [{"type": "tool_result", "tool_use_id": "t1",
                                                   "content": "Command failed", "is_error": True}]}}),
            json.dumps({"type": "assistant", "uuid": "u4", "parentUuid": "u3",
                         "message": {"role": "assistant",
                                     "content": [{"type": "text", "text": "An error occurred"}]}}),
        ]
        p = tmp_path / "error.jsonl"
        p.write_text("\n".join(lines) + "\n")
        session = Session(p)
        messages = extract_raw_messages(session.active_path())
        error_msgs = [m for m in messages if "tool_result" in m.role]
        assert len(error_msgs) == 1
        assert "ERROR" in error_msgs[0].content

    def test_compact_summary_role(self, compacted_session):
        path = compacted_session.active_path()
        messages = extract_raw_messages(path)
        compact_msgs = [m for m in messages if "compact_summary" in m.role]
        assert len(compact_msgs) >= 1
