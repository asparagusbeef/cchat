"""Shared fixtures for cchat test suite."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import cchat

# ── paths ──────────────────────────────────────────────────────────────────

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir():
    return FIXTURES_DIR


# ── per-fixture file paths ────────────────────────────────────────────────

@pytest.fixture
def simple_session_path():
    return FIXTURES_DIR / "simple_session.jsonl"


@pytest.fixture
def tool_session_path():
    return FIXTURES_DIR / "tool_session.jsonl"


@pytest.fixture
def branched_session_path():
    return FIXTURES_DIR / "branched_session.jsonl"


@pytest.fixture
def compacted_session_path():
    return FIXTURES_DIR / "compacted_session.jsonl"


@pytest.fixture
def complex_session_path():
    return FIXTURES_DIR / "complex_session.jsonl"


@pytest.fixture
def edge_cases_path():
    return FIXTURES_DIR / "edge_cases.jsonl"


# ── per-fixture Session objects ───────────────────────────────────────────

@pytest.fixture
def simple_session(simple_session_path):
    return cchat.Session(simple_session_path)


@pytest.fixture
def tool_session(tool_session_path):
    return cchat.Session(tool_session_path)


@pytest.fixture
def branched_session(branched_session_path):
    return cchat.Session(branched_session_path)


@pytest.fixture
def compacted_session(compacted_session_path):
    return cchat.Session(compacted_session_path)


@pytest.fixture
def complex_session(complex_session_path):
    return cchat.Session(complex_session_path)


@pytest.fixture
def edge_session(edge_cases_path):
    return cchat.Session(edge_cases_path)


# ── mock project directory ────────────────────────────────────────────────

@pytest.fixture
def mock_project_dir(tmp_path):
    """Create a mock project directory with fixture session files."""
    proj = tmp_path / "projects" / "-home-test"
    proj.mkdir(parents=True)

    # Copy fixture files as session files
    shutil.copy(FIXTURES_DIR / "simple_session.jsonl", proj / "sess-simple.jsonl")
    shutil.copy(FIXTURES_DIR / "tool_session.jsonl", proj / "sess-tool.jsonl")

    # Create an agent file that should be excluded
    agent_file = proj / "agent-test.jsonl"
    agent_file.write_text('{"type":"summary"}\n')

    return proj


@pytest.fixture
def mock_project_dir_full(tmp_path):
    """Mock project directory with ALL fixture session files."""
    proj = tmp_path / "projects" / "-home-test"
    proj.mkdir(parents=True)

    for name in ["simple_session", "tool_session", "branched_session",
                 "compacted_session", "complex_session"]:
        dest = f"sess-{name.replace('_', '-')}.jsonl"
        shutil.copy(FIXTURES_DIR / f"{name}.jsonl", proj / dest)

    # Agent file should be excluded
    (proj / "agent-test.jsonl").write_text('{"type":"summary"}\n')

    return proj


@pytest.fixture
def mock_project_dir_with_index(mock_project_dir):
    """Mock project directory that also has sessions-index.json."""
    shutil.copy(FIXTURES_DIR / "sessions-index.json", mock_project_dir / "sessions-index.json")
    return mock_project_dir


# ── mock claude directory (monkeypatched) ─────────────────────────────────

@pytest.fixture
def mock_claude_dir(tmp_path, monkeypatch):
    """Monkeypatch PROJECTS_DIR and CLAUDE_DIR to a temp directory."""
    claude_dir = tmp_path / ".claude"
    projects_dir = claude_dir / "projects"
    projects_dir.mkdir(parents=True)

    monkeypatch.setattr(cchat, "CLAUDE_DIR", claude_dir)
    monkeypatch.setattr(cchat, "PROJECTS_DIR", projects_dir)

    return claude_dir, projects_dir
