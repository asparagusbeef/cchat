#!/usr/bin/env python3
"""Browse and search Claude Code conversation history from the terminal."""

from __future__ import annotations

__version__ = "0.1.0"

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

# ═══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════

CLAUDE_DIR = Path.home() / ".claude"
PROJECTS_DIR = CLAUDE_DIR / "projects"
DEFAULT_TURNS = 5
MAX_WORKERS = 4

# Entry types that participate in the UUID tree
TREE_TYPES = {"user", "assistant", "system", "progress"}

# Entry types that are flat metadata (no UUID, not in tree)
METADATA_TYPES = {"summary", "file-history-snapshot", "queue-operation", "custom-title"}

# ═══════════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class ToolSummary:
    name: str
    input_data: dict

    def one_line(self) -> str:
        """Format tool call as a concise one-liner."""
        inp = self.input_data
        if self.name == "Read":
            path = inp.get("file_path", "?")
            return f"[Read] {_short_path(path)}"
        elif self.name == "Write":
            path = inp.get("file_path", "?")
            return f"[Write] {_short_path(path)}"
        elif self.name == "Edit":
            path = inp.get("file_path", "?")
            return f"[Edit] {_short_path(path)}"
        elif self.name == "Bash":
            cmd = inp.get("command", "?")
            desc = inp.get("description", "")
            label = desc if desc else (cmd[:60] + "..." if len(cmd) > 60 else cmd)
            return f"[Bash] {label}"
        elif self.name == "Glob":
            pattern = inp.get("pattern", "?")
            return f"[Glob] {pattern}"
        elif self.name == "Grep":
            pattern = inp.get("pattern", "?")
            return f"[Grep] {pattern}"
        elif self.name == "Task":
            desc = inp.get("description", "?")
            return f"[Task] {desc}"
        elif self.name == "WebFetch":
            url = inp.get("url", "?")
            return f"[WebFetch] {url[:60]}"
        elif self.name == "WebSearch":
            query = inp.get("query", "?")
            return f"[WebSearch] {query}"
        elif self.name == "TodoWrite" or self.name == "TaskCreate":
            return f"[{self.name}]"
        else:
            # Generic
            summary = json.dumps(inp)
            if len(summary) > 60:
                summary = summary[:60] + "..."
            return f"[{self.name}] {summary}"


@dataclass
class Turn:
    """A conversation turn: one user message + full assistant response."""
    user_text: str
    assistant_text: str
    tool_calls: list  # list[ToolSummary]
    timestamp: str
    uuid: str
    is_compact_summary: bool = False


@dataclass
class RawMessage:
    """A single raw message for --raw mode."""
    role: str  # "user", "assistant", "user (tool_result)", "assistant (tool)", "system", "thinking"
    content: str
    timestamp: str
    uuid: str
    entry_type: str  # original entry type


@dataclass
class SessionMeta:
    session_id: str
    summary: str
    first_prompt: str
    message_count: int
    created: str
    modified: str
    path: Optional[Path] = None


@dataclass
class BranchPoint:
    parent_uuid: str
    active_child_uuid: str
    alternative_uuids: list  # list[str]
    line_index: int  # file position of the parent entry


# ═══════════════════════════════════════════════════════════════════════════════
# UTILITIES
# ═══════════════════════════════════════════════════════════════════════════════


def _short_path(path: str, max_parts: int = 3) -> str:
    """Shorten a file path for display."""
    parts = Path(path).parts
    if len(parts) <= max_parts:
        return path
    return ".../" + "/".join(parts[-max_parts:])


def _parse_timestamp(ts: str) -> datetime:
    """Parse ISO timestamp, returning datetime.min on failure."""
    if not ts:
        return datetime.min
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return datetime.min


def _truncate(text: str, max_len: int) -> str:
    """Truncate text with ellipsis."""
    if max_len <= 0 or len(text) <= max_len:
        return text
    return text[:max_len] + "..."


# ═══════════════════════════════════════════════════════════════════════════════
# PROJECT RESOLUTION
# ═══════════════════════════════════════════════════════════════════════════════


class ProjectResolver:
    """Find and manage project directories."""

    @staticmethod
    def get_project_key(cwd: Path) -> str:
        """Convert cwd to Claude's project directory name format."""
        abs_path = str(cwd.resolve())
        return abs_path.replace("/", "-")

    @staticmethod
    def find_project_dir(cwd: Path) -> Optional[Path]:
        """Find Claude project directory for a working directory."""
        project_key = ProjectResolver.get_project_key(cwd)
        project_path = PROJECTS_DIR / project_key

        if project_path.exists():
            return project_path

        # Case-insensitive match (WSL path casing can vary)
        if PROJECTS_DIR.exists():
            for d in PROJECTS_DIR.iterdir():
                if d.is_dir() and d.name.lower() == project_key.lower():
                    return d
        return None

    @staticmethod
    def find_project_dir_for_path(project_path: str) -> Optional[Path]:
        """Find project dir from a user-provided path string."""
        # Normalize the path
        p = Path(project_path).resolve()
        return ProjectResolver.find_project_dir(p)

    @staticmethod
    def list_all_projects() -> list[dict]:
        """List all project directories with metadata."""
        if not PROJECTS_DIR.exists():
            return []

        projects = []
        for d in sorted(PROJECTS_DIR.iterdir()):
            if not d.is_dir():
                continue
            # Count session files (exclude agent- files and subdirectories)
            session_files = [
                f for f in d.glob("*.jsonl")
                if not f.name.startswith("agent-")
            ]
            if not session_files:
                continue

            # Decode project path from dir name
            decoded_path = d.name.replace("-", "/", 1)  # first dash is the leading /
            # Actually the format is: -mnt-c-Users-... where each - is a /
            decoded_path = d.name.replace("-", "/")
            if decoded_path.startswith("/"):
                pass  # already correct
            else:
                decoded_path = "/" + decoded_path

            latest_mtime = max(f.stat().st_mtime for f in session_files)
            projects.append({
                "dir": d,
                "name": d.name,
                "decoded_path": decoded_path,
                "session_count": len(session_files),
                "latest_modified": datetime.fromtimestamp(latest_mtime),
            })

        projects.sort(key=lambda p: p["latest_modified"], reverse=True)
        return projects

    @staticmethod
    def get_project_dir_or_exit(project_override: Optional[str] = None) -> Path:
        """Get project directory or exit with error."""
        if project_override:
            project_dir = ProjectResolver.find_project_dir_for_path(project_override)
            if not project_dir:
                # Try direct name match
                candidate = PROJECTS_DIR / project_override
                if candidate.exists():
                    return candidate
                # Try partial match
                if PROJECTS_DIR.exists():
                    for d in PROJECTS_DIR.iterdir():
                        if d.is_dir() and project_override.lower() in d.name.lower():
                            return d
                print(f"Error: No project found for '{project_override}'", file=sys.stderr)
                print("Use 'cchat projects' to list available projects.", file=sys.stderr)
                sys.exit(1)
            return project_dir

        cwd = Path.cwd()
        project_dir = ProjectResolver.find_project_dir(cwd)
        if not project_dir:
            print(f"Error: No Claude project found for {cwd}", file=sys.stderr)
            print(f"Expected: {PROJECTS_DIR / ProjectResolver.get_project_key(cwd)}", file=sys.stderr)
            print("Use 'cchat projects' to list available projects.", file=sys.stderr)
            print("Use '--project PATH' to specify a different project.", file=sys.stderr)
            sys.exit(1)
        return project_dir


# ═══════════════════════════════════════════════════════════════════════════════
# SESSION INDEX
# ═══════════════════════════════════════════════════════════════════════════════


class SessionIndex:
    """Fast session metadata with sessions-index.json + fallback."""

    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        self._index_cache: Optional[dict] = None

    def _load_index(self) -> dict:
        """Load sessions-index.json if present."""
        idx_path = self.project_dir / "sessions-index.json"
        if idx_path.exists():
            try:
                with open(idx_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return {e["sessionId"]: e for e in data.get("entries", [])}
            except (json.JSONDecodeError, KeyError):
                pass
        return {}

    def _get_index(self) -> dict:
        if self._index_cache is None:
            self._index_cache = self._load_index()
        return self._index_cache

    def get_metadata(self, session_id: str, jsonl_path: Path) -> SessionMeta:
        """Get session metadata. Fast path uses index, slow path reads file header."""
        idx = self._get_index()

        if session_id in idx:
            entry = idx[session_id]
            return SessionMeta(
                session_id=session_id,
                summary=entry.get("summary", ""),
                first_prompt=entry.get("firstPrompt", "")[:200],
                message_count=entry.get("messageCount", 0),
                created=entry.get("created", ""),
                modified=entry.get("modified", ""),
                path=jsonl_path,
            )

        # Slow path: read file header
        summary = ""
        first_prompt = ""
        custom_title = ""
        try:
            with open(jsonl_path, "r", encoding="utf-8", errors="replace") as f:
                for i, line in enumerate(f):
                    if i > 50:
                        break
                    try:
                        d = json.loads(line)
                        t = d.get("type")
                        if t == "summary" and not summary:
                            summary = d.get("summary", "")
                        elif t == "custom-title":
                            custom_title = d.get("customTitle", d.get("title", ""))
                        elif t == "user" and not first_prompt:
                            content = d.get("message", {}).get("content")
                            if isinstance(content, str) and content.strip():
                                first_prompt = content[:200]
                    except json.JSONDecodeError:
                        continue
        except OSError:
            pass

        # Quick message count: count lines with "user" or "assistant" type
        # (fast string search, no full JSON parse)
        msg_count = 0
        try:
            with open(jsonl_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if '"type":"user"' in line or '"type":"assistant"' in line:
                        msg_count += 1
        except OSError:
            pass

        stat = jsonl_path.stat()
        return SessionMeta(
            session_id=session_id,
            summary=custom_title or summary,
            first_prompt=first_prompt,
            message_count=msg_count,
            created="",
            modified=datetime.fromtimestamp(stat.st_mtime).isoformat(),
            path=jsonl_path,
        )

    def list_sessions(self, limit: int = 10) -> list[SessionMeta]:
        """List recent sessions sorted by modification time."""
        files = sorted(
            [f for f in self.project_dir.glob("*.jsonl") if not f.name.startswith("agent-")],
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        )

        if not files:
            return []

        results = []
        for f in files[:limit]:
            session_id = f.stem
            meta = self.get_metadata(session_id, f)
            results.append(meta)

        return results


# ═══════════════════════════════════════════════════════════════════════════════
# SESSION LOADER
# ═══════════════════════════════════════════════════════════════════════════════


class Session:
    """Lazy-loaded session with active path extraction and compaction stitching."""

    def __init__(self, jsonl_path: Path):
        self.path = jsonl_path
        self.session_id = jsonl_path.stem
        self._entries: Optional[list] = None
        self._by_uuid: Optional[dict] = None
        self._children: Optional[dict] = None
        self._entry_positions: Optional[dict] = None  # uuid -> file line index

    def _load(self):
        """Single-pass load of all entries."""
        entries = []
        by_uuid = {}
        positions = {}
        with open(self.path, "r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    entry["_line"] = i  # track file position
                    entries.append(entry)
                    uuid = entry.get("uuid")
                    if uuid:
                        by_uuid[uuid] = entry
                        positions[uuid] = i
                except json.JSONDecodeError:
                    continue
        self._entries = entries
        self._by_uuid = by_uuid
        self._entry_positions = positions

    @property
    def entries(self) -> list:
        if self._entries is None:
            self._load()
        return self._entries

    @property
    def by_uuid(self) -> dict:
        if self._by_uuid is None:
            self._load()
        return self._by_uuid

    @property
    def entry_positions(self) -> dict:
        if self._entry_positions is None:
            self._load()
        return self._entry_positions

    @property
    def children(self) -> dict:
        """Children map: parent_uuid -> [child_uuids]. Built on demand."""
        if self._children is None:
            self._children = defaultdict(list)
            for entry in self.entries:
                uuid = entry.get("uuid")
                parent = entry.get("parentUuid")
                if uuid and parent:
                    self._children[parent].append(uuid)
        return self._children

    def active_path(self, stitch: bool = True) -> list[dict]:
        """
        Extract the active conversation path.

        1. Find the last entry with a UUID (by file position)
        2. Walk backward via parentUuid
        3. At compact_boundary entries, optionally stitch via logicalParentUuid
        4. Return path in root-to-leaf order
        """
        # Find the last UUID entry that is NOT a sidechain and NOT progress
        last_entry = None
        for entry in reversed(self.entries):
            uuid = entry.get("uuid")
            if not uuid:
                continue
            if entry.get("isSidechain"):
                continue
            last_entry = entry
            break

        if not last_entry:
            return []

        # Walk backward
        raw_path = []
        current_uuid = last_entry.get("uuid")
        visited = set()

        while current_uuid and current_uuid not in visited:
            visited.add(current_uuid)
            entry = self.by_uuid.get(current_uuid)
            if not entry:
                if stitch and raw_path:
                    # Broken parent link (e.g., context continuation).
                    # Bridge by finding the last UUID entry before the
                    # earliest entry in our path so far.
                    earliest_line = min(
                        e.get("_line", float("inf")) for e in raw_path
                    )
                    fallback = None
                    for e in reversed(self.entries):
                        if e.get("_line", 0) >= earliest_line:
                            continue
                        if e.get("uuid") and e.get("type") != "progress":
                            fallback = e
                            break
                    if fallback and fallback["uuid"] not in visited:
                        current_uuid = fallback["uuid"]
                        continue
                break

            raw_path.append(entry)

            if entry.get("subtype") == "compact_boundary":
                if stitch:
                    # Jump to the entry before compaction
                    logical_parent = entry.get("logicalParentUuid")
                    if logical_parent and logical_parent in self.by_uuid:
                        current_uuid = logical_parent
                    else:
                        # logicalParentUuid target missing — fallback:
                        # find the last UUID entry before this compact_boundary
                        # in file order (it's part of the pre-compaction tree)
                        cb_line = entry.get("_line", float("inf"))
                        fallback = None
                        for e in reversed(self.entries):
                            if e.get("_line", 0) >= cb_line:
                                continue
                            if e.get("uuid") and e.get("type") != "progress":
                                fallback = e
                                break
                        if fallback:
                            current_uuid = fallback["uuid"]
                        else:
                            break
                else:
                    # No stitching, stop at compaction boundary
                    break
            else:
                current_uuid = entry.get("parentUuid")

        raw_path.reverse()
        return raw_path

    def branch_points(self) -> list[BranchPoint]:
        """
        Find true user-initiated branch points (excluding mechanical fan-out).

        A true branch is where a parent has multiple children that aren't just:
        - tool_use fan-out (assistant+tool_use -> {next_assistant, tool_result})
        - progress entry forks (progress + tool_result sharing parent)
        """
        active_set = set()
        for entry in self.active_path():
            uuid = entry.get("uuid")
            if uuid:
                active_set.add(uuid)

        branch_points = []
        checked_parents = set()

        for entry in self.active_path():
            parent_uuid = entry.get("parentUuid")
            if not parent_uuid or parent_uuid in checked_parents:
                continue
            checked_parents.add(parent_uuid)

            child_uuids = self.children.get(parent_uuid, [])
            if len(child_uuids) <= 1:
                continue

            # Check if this is mechanical fan-out
            if self._is_mechanical_fork(parent_uuid, child_uuids):
                continue

            # Real branch: find alternatives not on active path
            alternatives = [u for u in child_uuids if u not in active_set]
            if not alternatives:
                continue

            parent_entry = self.by_uuid.get(parent_uuid)
            branch_points.append(BranchPoint(
                parent_uuid=parent_uuid,
                active_child_uuid=entry.get("uuid", ""),
                alternative_uuids=alternatives,
                line_index=parent_entry.get("_line", 0) if parent_entry else 0,
            ))

        return branch_points

    def _is_mechanical_fork(self, parent_uuid: str, child_uuids: list) -> bool:
        """
        Returns True if the fork is a mechanical artifact, not a real user branch.

        Mechanical forks:
        1. tool_use fan-out: assistant(tool_use) -> {assistant(next block), user(tool_result)}
        2. progress fork: {progress, user(tool_result)} sharing assistant(tool_use) parent
        3. Multi-tool fan-out: multiple tool_results sharing same assistant parent
        """
        parent_entry = self.by_uuid.get(parent_uuid)
        if not parent_entry:
            return False

        parent_type = parent_entry.get("type")

        # Check child types
        child_types = set()
        child_has_tool_result = False
        child_has_progress = False
        for uuid in child_uuids:
            child = self.by_uuid.get(uuid)
            if not child:
                continue
            ct = child.get("type")
            child_types.add(ct)

            if ct == "user":
                content = child.get("message", {}).get("content")
                if isinstance(content, list):
                    child_has_tool_result = True
            elif ct == "progress":
                child_has_progress = True

        # Pattern 1: assistant parent with tool_use, children are {assistant, user(tool_result)}
        if parent_type == "assistant":
            blocks = parent_entry.get("message", {}).get("content", [])
            has_tool_use = any(
                isinstance(b, dict) and b.get("type") == "tool_use"
                for b in blocks
            )
            if has_tool_use:
                # Any fork from a tool_use assistant is mechanical
                return True

        # Pattern 2: progress entries mixed with other children
        if child_has_progress:
            # If all non-progress children are the same, it's mechanical
            non_progress = [u for u in child_uuids
                           if self.by_uuid.get(u, {}).get("type") != "progress"]
            if len(non_progress) <= 1:
                return True

        return False


# ═══════════════════════════════════════════════════════════════════════════════
# MESSAGE EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════════


def group_into_turns(raw_path: list[dict], mode: str = "text",
                     include_compact_summaries: bool = False) -> list[Turn]:
    """
    Group raw path entries into conversation turns.

    A turn = one user text message + the full assistant response
    (all text blocks concatenated across consecutive assistant entries).

    mode='text': user text + assistant text only
    mode='tools': also collect tool call summaries
    mode='raw': not used here (see extract_raw_messages)
    """
    turns = []
    current_turn: Optional[Turn] = None

    for entry in raw_path:
        entry_type = entry.get("type")

        # Skip non-conversation entries
        if entry_type in ("progress", "file-history-snapshot",
                          "queue-operation", "custom-title", "summary"):
            continue
        if entry_type == "system":
            continue

        if entry_type == "user":
            msg = entry.get("message", {})
            content = msg.get("content")

            # Extract text from user messages
            user_text = None
            if isinstance(content, str) and content.strip():
                user_text = content
            elif isinstance(content, list):
                # List content may have text blocks alongside tool_results
                text_parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        t = block.get("text", "").strip()
                        if t:
                            text_parts.append(t)
                if text_parts:
                    user_text = "\n".join(text_parts)

            if user_text:
                is_compact = bool(entry.get("isCompactSummary"))

                # Skip compact summaries unless requested
                if is_compact and not include_compact_summaries:
                    continue

                # Save previous turn
                if current_turn is not None:
                    turns.append(current_turn)

                current_turn = Turn(
                    user_text=user_text,
                    assistant_text="",
                    tool_calls=[],
                    timestamp=entry.get("timestamp", ""),
                    uuid=entry.get("uuid", ""),
                    is_compact_summary=is_compact,
                )

        elif entry_type == "assistant" and current_turn is not None:
            blocks = entry.get("message", {}).get("content", [])
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")

                if btype == "text":
                    text = block.get("text", "")
                    if text.strip():
                        if current_turn.assistant_text:
                            current_turn.assistant_text += "\n" + text
                        else:
                            current_turn.assistant_text = text

                elif btype == "tool_use" and mode == "tools":
                    current_turn.tool_calls.append(ToolSummary(
                        name=block.get("name", "?"),
                        input_data=block.get("input", {}),
                    ))

    # Don't forget the last turn
    if current_turn is not None:
        turns.append(current_turn)

    return turns


def extract_raw_messages(raw_path: list[dict], truncate_len: int = 500) -> list[RawMessage]:
    """
    Extract ALL messages from raw path for --raw mode.
    Includes tool calls, tool results, thinking blocks, system entries.
    """
    do_truncate = truncate_len > 0
    messages = []

    for entry in raw_path:
        entry_type = entry.get("type")

        # Skip non-content entries
        if entry_type in ("file-history-snapshot", "queue-operation",
                          "custom-title", "summary"):
            continue
        if entry_type == "progress":
            continue

        if entry_type == "system":
            subtype = entry.get("subtype", "")
            if subtype in ("compact_boundary", "microcompact_boundary"):
                content = entry.get("content", "")
                meta = ""
                if subtype == "compact_boundary":
                    cm = entry.get("compactMetadata", {})
                    meta = f" (trigger={cm.get('trigger', '?')}, preTokens={cm.get('preTokens', '?')})"
                elif subtype == "microcompact_boundary":
                    cm = entry.get("microcompactMetadata", {})
                    meta = f" (trigger={cm.get('trigger', '?')}, saved={cm.get('tokensSaved', '?')} tokens)"
                messages.append(RawMessage(
                    role=f"system ({subtype})",
                    content=f"{content}{meta}",
                    timestamp=entry.get("timestamp", ""),
                    uuid=entry.get("uuid", ""),
                    entry_type=entry_type,
                ))
            continue

        if entry_type == "user":
            msg = entry.get("message", {})
            content = msg.get("content")

            if isinstance(content, str):
                if content.strip():
                    role = "user"
                    if entry.get("isCompactSummary"):
                        role = "user (compact_summary)"
                    messages.append(RawMessage(
                        role=role,
                        content=content,
                        timestamp=entry.get("timestamp", ""),
                        uuid=entry.get("uuid", ""),
                        entry_type=entry_type,
                    ))
            elif isinstance(content, list):
                # Tool result
                parts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "tool_result":
                        tool_id = item.get("tool_use_id", "?")[:16]
                        result_content = ""
                        rc = item.get("content")
                        if isinstance(rc, str):
                            result_content = rc
                        elif isinstance(rc, list):
                            for sub in rc:
                                if isinstance(sub, dict) and sub.get("type") == "text":
                                    result_content += sub.get("text", "")
                        if do_truncate and len(result_content) > truncate_len:
                            result_content = result_content[:truncate_len] + "..."
                        is_err = item.get("is_error", False)
                        err_marker = " ERROR" if is_err else ""
                        parts.append(f"[tool_result {tool_id}{err_marker}]\n{result_content}")
                if parts:
                    messages.append(RawMessage(
                        role="user (tool_result)",
                        content="\n".join(parts),
                        timestamp=entry.get("timestamp", ""),
                        uuid=entry.get("uuid", ""),
                        entry_type=entry_type,
                    ))

        elif entry_type == "assistant":
            blocks = entry.get("message", {}).get("content", [])
            parts = []
            has_tool = False

            for block in blocks:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")

                if btype == "text":
                    text = block.get("text", "")
                    if text.strip():
                        parts.append(text)

                elif btype == "tool_use":
                    has_tool = True
                    name = block.get("name", "?")
                    tool_id = block.get("id", "")[:16]
                    inp = json.dumps(block.get("input", {}), indent=2)
                    tool_input_len = max(100, truncate_len * 3 // 5) if do_truncate else 0
                    if do_truncate and len(inp) > tool_input_len:
                        inp = inp[:tool_input_len] + "..."
                    parts.append(f"[tool_use: {name} ({tool_id})]\n{inp}")

                elif btype == "thinking":
                    thinking = block.get("thinking", "")
                    if thinking.strip():
                        thinking_len = max(100, truncate_len * 2 // 5) if do_truncate else 0
                        if do_truncate and len(thinking) > thinking_len:
                            thinking = thinking[:thinking_len] + "..."
                        parts.append(f"[thinking]\n{thinking}")

            if parts:
                role = "assistant (tool)" if has_tool else "assistant"
                messages.append(RawMessage(
                    role=role,
                    content="\n\n".join(parts),
                    timestamp=entry.get("timestamp", ""),
                    uuid=entry.get("uuid", ""),
                    entry_type=entry_type,
                ))

    return messages


# ═══════════════════════════════════════════════════════════════════════════════
# OUTPUT FORMATTING
# ═══════════════════════════════════════════════════════════════════════════════


def format_turn(turn: Turn, index: int, total: int,
                show_tools: bool = False, show_timestamp: bool = False) -> str:
    """Format a Turn for display."""
    lines = []

    # User message
    header = f"[{index}/{total}]"
    if show_timestamp and turn.timestamp:
        ts = _parse_timestamp(turn.timestamp)
        if ts != datetime.min:
            header += f" {ts.strftime('%H:%M:%S')}"
    lines.append(f"{header} USER")
    lines.append("─" * 60)
    if turn.is_compact_summary:
        lines.append("[Compaction Summary]")
    lines.append(turn.user_text)
    lines.append("")

    # Tool calls (if --tools mode)
    if show_tools and turn.tool_calls:
        for tc in turn.tool_calls:
            lines.append(f"  > {tc.one_line()}")
        lines.append("")

    # Assistant response
    if turn.assistant_text:
        lines.append(f"[{index}/{total}] ASSISTANT")
        if show_tools and turn.tool_calls:
            lines.append(f"({len(turn.tool_calls)} tool calls)")
        lines.append("─" * 60)
        lines.append(turn.assistant_text)
        lines.append("")

    return "\n".join(lines)


def format_raw_message(msg: RawMessage, index: int, total: int,
                       show_timestamp: bool = True) -> str:
    """Format a RawMessage for display."""
    header = f"[{index}/{total}] {msg.role.upper()}"
    if show_timestamp and msg.timestamp:
        ts = _parse_timestamp(msg.timestamp)
        if ts != datetime.min:
            header += f" ({ts.strftime('%H:%M:%S')})"
    if msg.uuid:
        header += f" uuid={msg.uuid[:12]}"

    return f"{header}\n{'─' * 60}\n{msg.content}\n"


def format_turns_json(turns: list[Turn], session_id: str, total: int,
                      start_index: int) -> str:
    """Format turns as JSON."""
    result = {
        "session_id": session_id,
        "total_turns": total,
        "turns": [],
    }
    for i, turn in enumerate(turns):
        t = {
            "index": start_index + i,
            "user": {
                "text": turn.user_text,
                "uuid": turn.uuid,
                "timestamp": turn.timestamp,
                "is_compact_summary": turn.is_compact_summary,
            },
            "assistant": {
                "text": turn.assistant_text,
            },
        }
        if turn.tool_calls:
            t["assistant"]["tool_calls"] = [
                {"name": tc.name, "summary": tc.one_line()}
                for tc in turn.tool_calls
            ]
        result["turns"].append(t)
    return json.dumps(result, indent=2, ensure_ascii=False)


def format_raw_json(messages: list[RawMessage], session_id: str) -> str:
    """Format raw messages as JSON."""
    result = {
        "session_id": session_id,
        "total_messages": len(messages),
        "messages": [
            {
                "role": msg.role,
                "content": msg.content,
                "uuid": msg.uuid,
                "timestamp": msg.timestamp,
            }
            for msg in messages
        ],
    }
    return json.dumps(result, indent=2, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════════════════════
# CLIPBOARD
# ═══════════════════════════════════════════════════════════════════════════════


def copy_to_clipboard(text: str) -> bool:
    """Copy text to clipboard using clip.exe (WSL)."""
    try:
        process = subprocess.Popen(
            ["clip.exe"],
            stdin=subprocess.PIPE,
            shell=False,
        )
        process.communicate(input=text.encode("utf-16-le"))
        return process.returncode == 0
    except Exception as e:
        print(f"Error copying to clipboard: {e}", file=sys.stderr)
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# SESSION RESOLUTION HELPERS
# ═══════════════════════════════════════════════════════════════════════════════


def resolve_session(project_dir: Path, session_arg: Optional[str]) -> Path:
    """Resolve session argument to a JSONL file path."""
    if session_arg is None:
        # Latest session by mtime
        files = sorted(
            [f for f in project_dir.glob("*.jsonl") if not f.name.startswith("agent-")],
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        )
        if not files:
            print("No sessions found.", file=sys.stderr)
            sys.exit(1)
        return files[0]

    # Numeric index: Nth from list
    if session_arg.isdigit():
        idx = int(session_arg)
        index = SessionIndex(project_dir)
        sessions = index.list_sessions(idx)
        if idx <= len(sessions):
            return sessions[idx - 1].path
        else:
            print(f"Error: Session index {session_arg} out of range (have {len(sessions)})", file=sys.stderr)
            sys.exit(1)

    # UUID prefix match
    matches = list(project_dir.glob(f"{session_arg}*.jsonl"))
    matches = [m for m in matches if not m.name.startswith("agent-")]
    if matches:
        if len(matches) == 1:
            return matches[0]
        else:
            print(f"Ambiguous session prefix '{session_arg}', matches:", file=sys.stderr)
            for m in matches[:5]:
                print(f"  {m.stem}", file=sys.stderr)
            sys.exit(1)

    print(f"Error: Session '{session_arg}' not found.", file=sys.stderr)
    print("Use 'cchat list' to see available sessions.", file=sys.stderr)
    sys.exit(1)


def parse_range(range_str: str, max_val: int) -> list[int]:
    """Parse a range string like '3', '3-7', '-1', '-3--1' into 1-based indices."""
    indices = []

    # Handle negative-to-negative range: -3--1
    m = re.match(r"^(-?\d+)--(-?\d+)$", range_str)
    if m:
        start, end = int(m.group(1)), -int(m.group(2))
    else:
        m = re.match(r"^(-?\d+)-(\d+)$", range_str)
        if m:
            start, end = int(m.group(1)), int(m.group(2))
        elif range_str.lstrip("-").isdigit():
            val = int(range_str)
            if val < 0:
                idx = max_val + val + 1
                return [idx] if 1 <= idx <= max_val else []
            else:
                return [val] if 1 <= val <= max_val else []
        else:
            print(f"Error: Invalid range '{range_str}'", file=sys.stderr)
            return []

    # Resolve negatives
    if start < 0:
        start = max_val + start + 1
    if end < 0:
        end = max_val + end + 1

    return [i for i in range(start, end + 1) if 1 <= i <= max_val]


def compute_indices(total: int, n: Optional[int], range_str: Optional[str],
                    show_all: bool) -> list[int]:
    """Compute which turn indices to show."""
    if show_all:
        return list(range(1, total + 1))
    elif range_str:
        return parse_range(range_str, total)
    elif n:
        start = max(0, total - n)
        return list(range(start + 1, total + 1))
    else:
        start = max(0, total - DEFAULT_TURNS)
        return list(range(start + 1, total + 1))


# ═══════════════════════════════════════════════════════════════════════════════
# COMMANDS
# ═══════════════════════════════════════════════════════════════════════════════


def cmd_list(args):
    """List recent sessions."""
    project_dir = ProjectResolver.get_project_dir_or_exit(args.project)
    index = SessionIndex(project_dir)
    sessions = index.list_sessions(args.count)

    if not sessions:
        print("No sessions found.")
        return

    print(f"Sessions in {project_dir.name}:\n")
    for i, s in enumerate(sessions, 1):
        modified = ""
        if s.modified:
            ts = _parse_timestamp(s.modified)
            if ts != datetime.min:
                modified = ts.strftime("%Y-%m-%d %H:%M")
            else:
                modified = s.modified[:16]
        msg_info = f"{s.message_count} msgs"
        print(f"[{i}] {s.session_id[:8]}... ({msg_info}, {modified})")

        display = s.summary or s.first_prompt
        if display:
            # Clean up and truncate
            display = display.replace("\n", " ").strip()
            if len(display) > 76:
                display = display[:76] + "..."
            print(f"    {display}")
        print()


def cmd_view(args):
    """View messages from a session."""
    project_dir = ProjectResolver.get_project_dir_or_exit(args.project)
    session_file = resolve_session(project_dir, args.session)
    session = Session(session_file)

    raw_path = session.active_path(stitch=not args.no_stitch)
    if not raw_path:
        print("No messages in this session.")
        return

    if args.raw:
        # Raw mode
        messages = extract_raw_messages(raw_path, truncate_len=args.truncate)
        total = len(messages)
        indices = compute_indices(total, args.n, args.r, args.all)

        if not indices:
            print(f"No messages match (1-{total} available)", file=sys.stderr)
            sys.exit(1)

        if args.json:
            selected = [messages[i - 1] for i in indices]
            print(format_raw_json(selected, session.session_id))
        else:
            print(f"Session: {session.session_id}")
            print(f"Showing {len(indices)} of {total} raw messages")
            print("=" * 60)
            for i in indices:
                print(format_raw_message(messages[i - 1], i, total))
    else:
        # Turn mode
        mode = "tools" if args.tools else "text"
        turns = group_into_turns(raw_path, mode=mode,
                                 include_compact_summaries=args.compact_summaries)

        # Fallback: if no turns found and compact summaries were hidden,
        # retry with them included (handles sessions where the only user
        # text is the continuation summary after compaction)
        if not turns and not args.compact_summaries:
            turns = group_into_turns(raw_path, mode=mode,
                                     include_compact_summaries=True)

        total = len(turns)

        if total == 0:
            print("No conversation turns in this session.")
            return

        indices = compute_indices(total, args.n, args.r, args.all)

        if not indices:
            print(f"No turns match (1-{total} available)", file=sys.stderr)
            sys.exit(1)

        if args.json:
            selected = [turns[i - 1] for i in indices]
            print(format_turns_json(selected, session.session_id, total, indices[0]))
        else:
            print(f"Session: {session.session_id}")
            print(f"Showing {len(indices)} of {total} turns")
            print("=" * 60)
            for i in indices:
                print(format_turn(turns[i - 1], i, total,
                                  show_tools=args.tools,
                                  show_timestamp=args.timestamps))


def cmd_copy(args):
    """Copy message(s) to clipboard."""
    project_dir = ProjectResolver.get_project_dir_or_exit(args.project)
    session_file = resolve_session(project_dir, args.session)
    session = Session(session_file)

    raw_path = session.active_path(stitch=True)
    if not raw_path:
        print("No messages in this session.", file=sys.stderr)
        sys.exit(1)

    if args.raw:
        messages = extract_raw_messages(raw_path, truncate_len=-1)
        total = len(messages)

        # Default: last message
        if args.r is None and args.n is None:
            args.r = "-1"

        indices = compute_indices(total, args.n, args.r, False)
        if not indices:
            print(f"No messages match (1-{total} available)", file=sys.stderr)
            sys.exit(1)

        texts = []
        for i in indices:
            msg = messages[i - 1]
            texts.append(f"**{msg.role.title()}:**\n\n{msg.content}")
        combined = "\n\n---\n\n".join(texts)
    else:
        mode = "tools" if args.tools else "text"
        turns = group_into_turns(raw_path, mode=mode)
        if not turns:
            turns = group_into_turns(raw_path, mode=mode,
                                     include_compact_summaries=True)
        total = len(turns)

        # Default: last turn's assistant response
        if args.r is None and args.n is None:
            args.r = "-1"

        indices = compute_indices(total, args.n, args.r, False)
        if not indices:
            print(f"No turns match (1-{total} available)", file=sys.stderr)
            sys.exit(1)

        texts = []
        for i in indices:
            turn = turns[i - 1]
            parts = []
            if turn.user_text:
                parts.append(f"**User:**\n\n{turn.user_text}")
            if turn.assistant_text:
                parts.append(f"**Assistant:**\n\n{turn.assistant_text}")
            texts.append("\n\n".join(parts))
        combined = "\n\n---\n\n".join(texts)

    if copy_to_clipboard(combined):
        if len(indices) == 1:
            print(f"Copied turn #{indices[0]} to clipboard ({len(combined)} chars)")
        else:
            print(f"Copied {len(indices)} turns (#{indices[0]}-#{indices[-1]}) to clipboard ({len(combined)} chars)")
    else:
        print("Failed to copy to clipboard", file=sys.stderr)
        sys.exit(1)


def cmd_projects(args):
    """List all projects."""
    projects = ProjectResolver.list_all_projects()

    if not projects:
        print("No projects found.")
        return

    print(f"Projects ({len(projects)}):\n")
    for i, p in enumerate(projects, 1):
        modified = p["latest_modified"].strftime("%Y-%m-%d %H:%M")
        print(f"[{i}] {p['decoded_path']}")
        print(f"    {p['session_count']} sessions, last active: {modified}")
        print(f"    key: {p['name']}")
        print()


def cmd_search(args):
    """Search across sessions for a pattern."""
    project_dir = ProjectResolver.get_project_dir_or_exit(args.project)
    pattern = args.pattern
    limit = args.limit

    files = sorted(
        [f for f in project_dir.glob("*.jsonl") if not f.name.startswith("agent-")],
        key=lambda x: x.stat().st_mtime,
        reverse=True,
    )

    if not files:
        print("No sessions to search.")
        return

    pattern_lower = pattern.lower()
    results = []

    for f in files:
        if len(results) >= limit:
            break
        try:
            with open(f, "r", encoding="utf-8", errors="replace") as fp:
                for line_num, line in enumerate(fp):
                    if len(results) >= limit:
                        break
                    if pattern_lower not in line.lower():
                        continue
                    try:
                        entry = json.loads(line)
                        entry_type = entry.get("type")
                        if entry_type not in ("user", "assistant"):
                            continue
                        msg = entry.get("message", {})
                        content = msg.get("content")

                        # Extract searchable text
                        text = ""
                        if isinstance(content, str):
                            text = content
                        elif isinstance(content, list):
                            for block in content:
                                if isinstance(block, dict) and block.get("type") == "text":
                                    text += block.get("text", "")

                        if pattern_lower in text.lower():
                            # Find the match context
                            idx = text.lower().index(pattern_lower)
                            start = max(0, idx - 40)
                            end = min(len(text), idx + len(pattern) + 40)
                            snippet = text[start:end].replace("\n", " ")
                            if start > 0:
                                snippet = "..." + snippet
                            if end < len(text):
                                snippet = snippet + "..."

                            results.append({
                                "session_id": f.stem,
                                "role": entry_type,
                                "snippet": snippet,
                                "timestamp": entry.get("timestamp", ""),
                                "file": f,
                            })
                    except json.JSONDecodeError:
                        continue
        except OSError:
            continue

    if not results:
        print(f"No matches for '{pattern}'.")
        return

    print(f"Found {len(results)} match{'es' if len(results) != 1 else ''} for '{pattern}':\n")
    for i, r in enumerate(results, 1):
        ts = ""
        if r["timestamp"]:
            parsed = _parse_timestamp(r["timestamp"])
            if parsed != datetime.min:
                ts = parsed.strftime("%Y-%m-%d %H:%M")
        print(f"[{i}] {r['session_id'][:8]}... ({r['role']}, {ts})")
        print(f"    {r['snippet']}")
        print()


def cmd_tree(args):
    """Show conversation tree structure."""
    project_dir = ProjectResolver.get_project_dir_or_exit(args.project)
    session_file = resolve_session(project_dir, args.session)
    session = Session(session_file)

    raw_path = session.active_path(stitch=True)
    if not raw_path:
        print("No messages in this session.")
        return

    turns = group_into_turns(raw_path, mode="text")
    branch_points = session.branch_points()

    # Build a set of UUIDs that are branch parents
    branch_parent_uuids = {bp.parent_uuid for bp in branch_points}

    print(f"Session: {session.session_id}")
    print(f"Turns: {len(turns)}, Branch points: {len(branch_points)}")
    print("=" * 60)

    # Show turns with branch markers
    for i, turn in enumerate(turns, 1):
        prefix = "├──" if i < len(turns) else "└──"
        user_preview = turn.user_text.replace("\n", " ")[:60]
        if len(turn.user_text) > 60:
            user_preview += "..."

        print(f"{prefix} [{i}] User: {user_preview}")

        if turn.assistant_text:
            asst_preview = turn.assistant_text.replace("\n", " ")[:60]
            if len(turn.assistant_text) > 60:
                asst_preview += "..."
            indent = "│   " if i < len(turns) else "    "
            print(f"{indent}  Assistant: {asst_preview}")

            if turn.tool_calls:
                print(f"{indent}  ({len(turn.tool_calls)} tool calls)")

    if branch_points:
        print(f"\nBranch Points ({len(branch_points)}):")
        print("─" * 40)
        for bp in branch_points:
            parent_entry = session.by_uuid.get(bp.parent_uuid, {})
            parent_type = parent_entry.get("type", "?")
            n_alts = len(bp.alternative_uuids)
            print(f"  At {bp.parent_uuid[:12]}... ({parent_type}): "
                  f"{n_alts} alternative{'s' if n_alts != 1 else ''}")


def cmd_export(args):
    """Export full session."""
    project_dir = ProjectResolver.get_project_dir_or_exit(args.project)
    session_file = resolve_session(project_dir, args.session)
    session = Session(session_file)

    raw_path = session.active_path(stitch=True)
    if not raw_path:
        print("No messages in this session.")
        return

    if args.json:
        if args.raw:
            messages = extract_raw_messages(raw_path, truncate_len=-1)
            print(format_raw_json(messages, session.session_id))
        else:
            mode = "tools" if args.include_tools else "text"
            turns = group_into_turns(raw_path, mode=mode,
                                     include_compact_summaries=True)
            print(format_turns_json(turns, session.session_id, len(turns), 1))
    else:
        # Markdown export
        mode = "tools" if args.include_tools else "text"
        turns = group_into_turns(raw_path, mode=mode,
                                 include_compact_summaries=True)
        if not turns:
            print("No conversation turns.")
            return

        print(f"# Session {session.session_id}")
        print(f"**Turns:** {len(turns)}")
        print()
        for i, turn in enumerate(turns, 1):
            print(format_turn(turn, i, len(turns),
                              show_tools=args.include_tools,
                              show_timestamp=True))


# ═══════════════════════════════════════════════════════════════════════════════
# CLI PARSER
# ═══════════════════════════════════════════════════════════════════════════════


def _add_project_arg(p):
    """Add --project/-p to a subparser."""
    p.add_argument("--project", "-p", metavar="PATH",
                   help="Use project at PATH instead of cwd")
    return p


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cchat",
        description="Claude Code Chat History Browser - Browse, search, and copy messages",
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # list
    list_p = subparsers.add_parser("list", aliases=["ls"],
                                   help="List recent sessions")
    _add_project_arg(list_p)
    list_p.add_argument("count", nargs="?", type=int, default=10,
                        help="Number of sessions (default: 10)")

    # view
    view_p = subparsers.add_parser("view", aliases=["v"],
                                   help="View conversation messages")
    _add_project_arg(view_p)
    view_p.add_argument("session", nargs="?",
                        help="Session index or UUID prefix (default: latest)")
    view_p.add_argument("-n", type=int, metavar="N",
                        help="Show last N turns")
    view_p.add_argument("-r", metavar="RANGE",
                        help="Show specific turns: 10, 5-10, -1, -3--1")
    view_p.add_argument("--all", action="store_true",
                        help="Show all turns")
    view_p.add_argument("--tools", action="store_true",
                        help="Show tool call summaries")
    view_p.add_argument("--raw", action="store_true",
                        help="Show everything (tool IO, thinking, system)")
    view_p.add_argument("--json", action="store_true",
                        help="Output as JSON")
    view_p.add_argument("--no-stitch", action="store_true",
                        help="Don't bridge compaction boundaries")
    view_p.add_argument("--timestamps", action="store_true",
                        help="Show timestamps")
    view_p.add_argument("--compact-summaries", action="store_true",
                        help="Include compaction summary messages")
    view_p.add_argument("--truncate", type=int, default=500, metavar="LEN",
                        help="Truncate length for raw content (default: 500, -1=none)")

    # copy
    copy_p = subparsers.add_parser("copy", aliases=["cp"],
                                   help="Copy messages to clipboard")
    _add_project_arg(copy_p)
    copy_p.add_argument("session", nargs="?",
                        help="Session index or UUID prefix")
    copy_p.add_argument("-n", type=int, metavar="N",
                        help="Copy last N turns")
    copy_p.add_argument("-r", metavar="RANGE",
                        help="Copy specific turns (default: -1)")
    copy_p.add_argument("--tools", action="store_true",
                        help="Include tool summaries")
    copy_p.add_argument("--raw", action="store_true",
                        help="Copy raw messages")

    # projects (no --project flag needed)
    subparsers.add_parser("projects", help="List all projects")

    # search
    search_p = subparsers.add_parser("search", aliases=["s"],
                                     help="Search across sessions")
    _add_project_arg(search_p)
    search_p.add_argument("pattern", help="Search pattern")
    search_p.add_argument("--limit", type=int, default=20,
                          help="Max results (default: 20)")

    # tree
    tree_p = subparsers.add_parser("tree", help="Show conversation tree structure")
    _add_project_arg(tree_p)
    tree_p.add_argument("session", nargs="?",
                        help="Session index or UUID prefix")

    # export
    export_p = subparsers.add_parser("export", help="Export full session")
    _add_project_arg(export_p)
    export_p.add_argument("session", nargs="?",
                          help="Session index or UUID prefix")
    export_p.add_argument("--json", action="store_true",
                          help="Export as JSON (default: markdown)")
    export_p.add_argument("--raw", action="store_true",
                          help="Export raw messages")
    export_p.add_argument("--include-tools", action="store_true",
                          help="Include tool calls in export")

    return parser


def _preprocess_argv(argv: list[str]) -> list[str]:
    """Fix argparse issue with -r and negative ranges like -3--1.

    argparse can't handle '-r -3--1' because '-3--1' starts with '-'
    and isn't a valid negative number, so argparse rejects it.
    We normalize '-r <range>' to '-r=<range>' when the range looks valid.
    """
    result = []
    i = 0
    range_pat = re.compile(r'^-?\d+(--?\d+)?$')
    while i < len(argv):
        if argv[i] == '-r' and i + 1 < len(argv) and range_pat.match(argv[i + 1]):
            result.append(f'-r={argv[i + 1]}')
            i += 2
        else:
            result.append(argv[i])
            i += 1
    return result


def main():
    parser = build_parser()
    args = parser.parse_args(_preprocess_argv(sys.argv[1:]))

    # Default command: view
    if args.command is None:
        # Show help if no command
        parser.print_help()
        sys.exit(0)

    commands = {
        "list": cmd_list,
        "ls": cmd_list,
        "view": cmd_view,
        "v": cmd_view,
        "copy": cmd_copy,
        "cp": cmd_copy,
        "projects": cmd_projects,
        "search": cmd_search,
        "s": cmd_search,
        "tree": cmd_tree,
        "export": cmd_export,
    }

    cmd = commands.get(args.command)
    if cmd:
        cmd(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
