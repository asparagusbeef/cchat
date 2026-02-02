"""Tests for SessionIndex: get_metadata fast/slow path, list_sessions, caching."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cchat import SessionIndex, SessionMeta


# ── Fast path (with index file) ──────────────────────────────────────────

class TestSessionIndexFastPath:
    def test_get_metadata_from_index(self, mock_project_dir_with_index):
        index = SessionIndex(mock_project_dir_with_index)
        meta = index.get_metadata("sess-simple",
                                   mock_project_dir_with_index / "sess-simple.jsonl")
        assert meta.session_id == "sess-simple"
        assert meta.summary == "Simple test conversation"
        assert meta.first_prompt == "Hello"
        assert meta.message_count == 6

    def test_list_sessions_from_index(self, mock_project_dir_with_index):
        index = SessionIndex(mock_project_dir_with_index)
        sessions = index.list_sessions(limit=10)
        assert len(sessions) == 2
        # All should have session_ids
        ids = {s.session_id for s in sessions}
        assert "sess-simple" in ids
        assert "sess-tool" in ids


# ── Slow path (no index file) ────────────────────────────────────────────

class TestSessionIndexSlowPath:
    def test_get_metadata_without_index(self, mock_project_dir):
        index = SessionIndex(mock_project_dir)
        meta = index.get_metadata("sess-simple",
                                   mock_project_dir / "sess-simple.jsonl")
        assert meta.session_id == "sess-simple"
        assert meta.summary == "Simple test conversation"
        assert meta.first_prompt == "Hello"
        assert meta.message_count > 0


# ── list_sessions ─────────────────────────────────────────────────────────

class TestListSessions:
    def test_sorted_by_mtime(self, mock_project_dir):
        import time
        # Touch sess-simple to make it newer
        simple = mock_project_dir / "sess-simple.jsonl"
        time.sleep(0.05)
        simple.write_text(simple.read_text())  # rewrite to update mtime

        index = SessionIndex(mock_project_dir)
        sessions = index.list_sessions(limit=10)
        assert sessions[0].session_id == "sess-simple"

    def test_limit_respected(self, mock_project_dir):
        index = SessionIndex(mock_project_dir)
        sessions = index.list_sessions(limit=1)
        assert len(sessions) == 1

    def test_agent_files_excluded(self, mock_project_dir):
        index = SessionIndex(mock_project_dir)
        sessions = index.list_sessions(limit=100)
        for s in sessions:
            assert not s.session_id.startswith("agent-")


# ── Caching ───────────────────────────────────────────────────────────────

class TestSessionIndexCaching:
    def test_cache_returns_same_object(self, mock_project_dir_with_index):
        index = SessionIndex(mock_project_dir_with_index)
        cache1 = index._get_index()
        cache2 = index._get_index()
        assert cache1 is cache2


# ── Corrupt index ─────────────────────────────────────────────────────────

class TestCorruptIndex:
    def test_corrupt_index_falls_back(self, mock_project_dir):
        # Write corrupt JSON to index
        idx_path = mock_project_dir / "sessions-index.json"
        idx_path.write_text("{{{invalid json")

        index = SessionIndex(mock_project_dir)
        # Should not raise, falls back to empty index
        meta = index.get_metadata("sess-simple",
                                   mock_project_dir / "sess-simple.jsonl")
        assert meta.session_id == "sess-simple"
        # Should still get data from slow path
        assert meta.first_prompt == "Hello"
