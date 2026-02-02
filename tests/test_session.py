"""Tests for Session: loading, tree building, active_path, branches, compaction stitching."""

from __future__ import annotations

import pytest

import cchat
from cchat import Session


# ── Loading ───────────────────────────────────────────────────────────────

class TestSessionLoading:
    def test_entry_count_simple(self, simple_session):
        # summary + 6 entries = 7
        assert len(simple_session.entries) == 7

    def test_by_uuid_populated(self, simple_session):
        assert "uuid-0001" in simple_session.by_uuid
        assert "uuid-0006" in simple_session.by_uuid

    def test_summary_has_no_uuid(self, simple_session):
        # summary entry has no uuid, so not in by_uuid
        assert len(simple_session.by_uuid) == 6

    def test_malformed_json_skipped(self, edge_session):
        # First line is invalid JSON, should be skipped
        for entry in edge_session.entries:
            assert isinstance(entry, dict)

    def test_positions_tracked(self, simple_session):
        positions = simple_session.entry_positions
        assert positions["uuid-0001"] == 1  # line 0 is summary
        assert positions["uuid-0006"] == 6

    def test_lazy_loading(self, simple_session_path):
        session = Session(simple_session_path)
        assert session._entries is None
        _ = session.entries
        assert session._entries is not None

    def test_tool_session_entry_count(self, tool_session):
        # summary + 11 entries = 12 (assistant entries split into text + tool_use lines)
        assert len(tool_session.entries) == 12


# ── Children map ──────────────────────────────────────────────────────────

class TestChildrenMap:
    def test_simple_chain(self, simple_session):
        children = simple_session.children
        assert "uuid-0002" in children["uuid-0001"]
        assert "uuid-0003" in children["uuid-0002"]

    def test_tool_fork_has_multiple_children(self, tool_session):
        # uuid-1002b (assistant tool_use chunk) has 2 children:
        # uuid-1003 (progress) and uuid-1004 (tool_result)
        children = tool_session.children
        assert len(children["uuid-1002b"]) == 2
        child_uuids = set(children["uuid-1002b"])
        assert "uuid-1003" in child_uuids
        assert "uuid-1004" in child_uuids

    def test_branched_parent_has_two_children(self, branched_session):
        children = branched_session.children
        child_uuids = set(children["uuid-2002"])
        assert "uuid-2003" in child_uuids
        assert "uuid-2005" in child_uuids


# ── Logical parent map ────────────────────────────────────────────────────

class TestLogicalParentMap:
    def test_compacted_session_has_entry(self, compacted_session):
        lpm = compacted_session.logical_parent_map
        assert "uuid-3004" in lpm
        assert lpm["uuid-3004"] == "uuid-3005"

    def test_simple_session_empty(self, simple_session):
        assert simple_session.logical_parent_map == {}

    def test_complex_session_microcompact_not_in_logical_map(self, complex_session):
        lpm = complex_session.logical_parent_map
        # Real microcompact boundaries do NOT have logicalParentUuid,
        # so they should NOT appear in the logical parent map.
        # They chain via normal parentUuid instead.
        assert "uuid-4009" not in lpm


# ── _find_last_uuid ──────────────────────────────────────────────────────

class TestFindLastUuid:
    def test_returns_last_entry(self, simple_session):
        last = simple_session._find_last_uuid()
        assert last["uuid"] == "uuid-0006"

    def test_skips_sidechain(self, tmp_path):
        """Last entry with isSidechain=true should be skipped."""
        p = tmp_path / "sidechain.jsonl"
        import json
        lines = [
            json.dumps({"type": "user", "uuid": "u1", "parentUuid": None,
                         "message": {"role": "user", "content": "Hi"}}),
            json.dumps({"type": "assistant", "uuid": "u2", "parentUuid": "u1",
                         "message": {"role": "assistant", "content": [{"type": "text", "text": "Hello"}]}}),
            json.dumps({"type": "assistant", "uuid": "u3", "parentUuid": "u1",
                         "message": {"role": "assistant", "content": [{"type": "text", "text": "Sidechain"}]},
                         "isSidechain": True}),
        ]
        p.write_text("\n".join(lines) + "\n")
        session = Session(p)
        last = session._find_last_uuid()
        assert last["uuid"] == "u2"


# ── _walk_backward ────────────────────────────────────────────────────────

class TestWalkBackward:
    def test_simple_walk(self, simple_session):
        path = simple_session._walk_backward("uuid-0006")
        uuids = [e["uuid"] for e in path]
        assert uuids == ["uuid-0001", "uuid-0002", "uuid-0003",
                         "uuid-0004", "uuid-0005", "uuid-0006"]

    def test_compaction_stitch(self, compacted_session):
        path = compacted_session._walk_backward("uuid-3009", stitch=True)
        uuids = [e["uuid"] for e in path]
        # Should cross the compact boundary back to pre-compaction entries
        assert "uuid-3001" in uuids
        assert "uuid-3009" in uuids

    def test_no_stitch_stops_at_boundary(self, compacted_session):
        path = compacted_session._walk_backward("uuid-3009", stitch=False)
        uuids = [e["uuid"] for e in path]
        # Should NOT include pre-compaction entries
        assert "uuid-3001" not in uuids
        assert "uuid-3005" in uuids  # compact_boundary is the root


# ── active_path ───────────────────────────────────────────────────────────

class TestActivePath:
    def test_simple_linear(self, simple_session):
        path = simple_session.active_path()
        uuids = [e["uuid"] for e in path]
        assert uuids == ["uuid-0001", "uuid-0002", "uuid-0003",
                         "uuid-0004", "uuid-0005", "uuid-0006"]

    def test_branched_follows_latest(self, branched_session):
        path = branched_session.active_path()
        uuids = [e["uuid"] for e in path]
        # Active path should follow latest branch (uuid-2005, line 5 > uuid-2003, line 3)
        assert "uuid-2005" in uuids
        assert "uuid-2006" in uuids
        assert "uuid-2003" not in uuids

    def test_compacted_stitched(self, compacted_session):
        path = compacted_session.active_path(stitch=True)
        uuids = [e["uuid"] for e in path]
        assert "uuid-3001" in uuids
        assert "uuid-3009" in uuids

    def test_compacted_no_stitch(self, compacted_session):
        path = compacted_session.active_path(stitch=False)
        uuids = [e["uuid"] for e in path]
        assert "uuid-3001" not in uuids
        # Path starts from compact boundary
        assert "uuid-3005" in uuids

    def test_tool_session_active_path(self, tool_session):
        path = tool_session.active_path()
        uuids = [e["uuid"] for e in path]
        # Should follow through tool_result chain
        assert "uuid-1001" in uuids
        assert "uuid-1009" in uuids

    def test_empty_session(self, tmp_path):
        p = tmp_path / "empty.jsonl"
        p.write_text("")
        session = Session(p)
        assert session.active_path() == []


# ── _branch_path ──────────────────────────────────────────────────────────

class TestBranchPath:
    def test_branch_1_includes_prefix(self, branched_session):
        path = branched_session.active_path(branch=1)
        uuids = [e["uuid"] for e in path]
        # Branch 1 = uuid-2003 (first child by file position)
        assert "uuid-2001" in uuids  # common prefix
        assert "uuid-2002" in uuids  # common prefix
        assert "uuid-2003" in uuids  # branch 1
        assert "uuid-2004" in uuids  # branch 1 response

    def test_branch_2(self, branched_session):
        path = branched_session.active_path(branch=2)
        uuids = [e["uuid"] for e in path]
        # Branch 2 = uuid-2005 (second child by file position)
        assert "uuid-2001" in uuids
        assert "uuid-2005" in uuids
        assert "uuid-2006" in uuids

    def test_out_of_range_exits(self, branched_session):
        with pytest.raises(SystemExit):
            branched_session.active_path(branch=5)


# ── _is_mechanical_fork ──────────────────────────────────────────────────

class TestIsMechanicalFork:
    def test_tool_use_fork_is_mechanical(self, tool_session):
        # uuid-1002b is assistant with tool_use, children are progress + tool_result
        child_uuids = tool_session.children["uuid-1002b"]
        assert tool_session._is_mechanical_fork("uuid-1002b", child_uuids) is True

    def test_real_branch_is_not_mechanical(self, branched_session):
        # uuid-2002 is assistant WITHOUT tool_use
        child_uuids = branched_session.children["uuid-2002"]
        assert branched_session._is_mechanical_fork("uuid-2002", child_uuids) is False

    def test_progress_only_fork_is_mechanical(self, tmp_path):
        """Progress + single non-progress child = mechanical."""
        import json
        lines = [
            json.dumps({"type": "assistant", "uuid": "p1", "parentUuid": None,
                         "message": {"role": "assistant", "content": [{"type": "text", "text": "Hi"}]}}),
            json.dumps({"type": "progress", "uuid": "c1", "parentUuid": "p1"}),
            json.dumps({"type": "user", "uuid": "c2", "parentUuid": "p1",
                         "message": {"role": "user", "content": "Next"}}),
        ]
        p = tmp_path / "prog.jsonl"
        p.write_text("\n".join(lines) + "\n")
        session = Session(p)
        assert session._is_mechanical_fork("p1", ["c1", "c2"]) is True


# ── branch_points ─────────────────────────────────────────────────────────

class TestBranchPoints:
    def test_simple_no_branches(self, simple_session):
        assert simple_session.branch_points() == []

    def test_tool_session_no_branches(self, tool_session):
        # Tool forks are mechanical, not real branches
        assert tool_session.branch_points() == []

    def test_branched_has_one_point(self, branched_session):
        bps = branched_session.branch_points()
        assert len(bps) == 1
        assert bps[0].parent_uuid == "uuid-2002"

    def test_branched_alternatives(self, branched_session):
        bps = branched_session.branch_points()
        # Active path follows uuid-2005 (latest), so uuid-2003 is alternative
        assert "uuid-2003" in bps[0].alternative_uuids


# ── get_branch_info ───────────────────────────────────────────────────────

class TestGetBranchInfo:
    def test_simple_no_info(self, simple_session):
        assert simple_session.get_branch_info() == []

    def test_branched_session_info(self, branched_session):
        infos = branched_session.get_branch_info()
        assert len(infos) == 1
        bi = infos[0]
        assert bi.parent_uuid == "uuid-2002"
        assert len(bi.children) == 2

    def test_branch_children_previews(self, branched_session):
        infos = branched_session.get_branch_info()
        bi = infos[0]
        previews = [c.preview for c in bi.children]
        assert any("option A" in p for p in previews)
        assert any("option B" in p for p in previews)

    def test_branch_children_is_active(self, branched_session):
        infos = branched_session.get_branch_info()
        bi = infos[0]
        active_children = [c for c in bi.children if c.is_active]
        assert len(active_children) == 1
        # The active child should be uuid-2005 (later in file)
        assert active_children[0].child_uuid == "uuid-2005"

    def test_complex_session_has_branch(self, complex_session):
        infos = complex_session.get_branch_info()
        assert len(infos) >= 1
