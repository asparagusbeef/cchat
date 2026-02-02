"""Tests for utility functions: _short_path, _parse_timestamp, _truncate, _strip_ansi, parse_range, compute_indices."""

from __future__ import annotations

from datetime import datetime

import pytest

import cchat
from cchat import (
    _short_path,
    _parse_timestamp,
    _truncate,
    _strip_ansi,
    parse_range,
    compute_indices,
    DEFAULT_TURNS,
)


# ── _short_path ───────────────────────────────────────────────────────────

class TestShortPath:
    def test_already_short(self):
        assert _short_path("/a/b") == "/a/b"

    def test_exact_max_parts(self):
        # /a/b has parts ('/', 'a', 'b') = 3 parts, no truncation
        assert _short_path("/a/b", max_parts=3) == "/a/b"

    def test_truncation(self):
        # ('/', 'home', 'user', 'projects', 'deep', 'file.py') = 6 parts, default max_parts=3
        result = _short_path("/home/user/projects/deep/file.py")
        assert result == ".../projects/deep/file.py"

    def test_custom_max_parts(self):
        result = _short_path("/a/b/c/d/e", max_parts=2)
        assert result == ".../d/e"

    def test_single_component(self):
        assert _short_path("file.py") == "file.py"


# ── _parse_timestamp ──────────────────────────────────────────────────────

class TestParseTimestamp:
    def test_valid_iso_z(self):
        result = _parse_timestamp("2025-01-15T10:00:00Z")
        assert result.year == 2025
        assert result.month == 1
        assert result.hour == 10

    def test_valid_iso_offset(self):
        result = _parse_timestamp("2025-01-15T10:00:00+02:00")
        assert result != datetime.min

    def test_empty_string(self):
        assert _parse_timestamp("") == datetime.min

    def test_none(self):
        assert _parse_timestamp(None) == datetime.min

    def test_garbage(self):
        assert _parse_timestamp("not-a-date") == datetime.min

    def test_numeric_string(self):
        assert _parse_timestamp("12345") == datetime.min


# ── _truncate ─────────────────────────────────────────────────────────────

class TestTruncate:
    def test_no_truncation_needed(self):
        assert _truncate("hello", 10) == "hello"

    def test_truncation(self):
        assert _truncate("hello world", 5) == "hello..."

    def test_zero_max(self):
        assert _truncate("hello", 0) == "hello"

    def test_negative_max(self):
        assert _truncate("hello", -5) == "hello"

    def test_exact_length(self):
        assert _truncate("hello", 5) == "hello"

    def test_empty_string(self):
        assert _truncate("", 10) == ""


# ── _strip_ansi ───────────────────────────────────────────────────────────

class TestStripAnsi:
    def test_no_codes(self):
        assert _strip_ansi("plain text") == "plain text"

    def test_color_code(self):
        assert _strip_ansi("\x1b[31mred\x1b[0m") == "red"

    def test_bold_reset(self):
        assert _strip_ansi("\x1b[1mbold\x1b[0m") == "bold"

    def test_multi_param_codes(self):
        assert _strip_ansi("\x1b[1;31;42mfancy\x1b[0m") == "fancy"

    def test_multiple_codes(self):
        assert _strip_ansi("\x1b[32mgreen\x1b[0m and \x1b[34mblue\x1b[0m") == "green and blue"

    def test_empty_string(self):
        assert _strip_ansi("") == ""


# ── parse_range ───────────────────────────────────────────────────────────

class TestParseRange:
    def test_single_positive(self):
        assert parse_range("3", 10) == [3]

    def test_single_negative(self):
        # -1 with max_val=10 -> index 10
        assert parse_range("-1", 10) == [10]

    def test_single_negative_middle(self):
        # -3 with max_val=10 -> index 8
        assert parse_range("-3", 10) == [8]

    def test_positive_range(self):
        assert parse_range("3-5", 10) == [3, 4, 5]

    def test_negative_to_negative(self):
        # -3--1 with max_val=10 -> 8, 9, 10
        assert parse_range("-3--1", 10) == [8, 9, 10]

    def test_negative_to_positive(self):
        # -2-10 with max_val=10 -> 9, 10
        assert parse_range("-2-10", 10) == [9, 10]

    def test_out_of_range_positive(self):
        assert parse_range("15", 10) == []

    def test_out_of_range_negative(self):
        # -15 with max_val=10 -> index -4 -> out of range
        assert parse_range("-15", 10) == []

    def test_invalid_string(self):
        assert parse_range("abc", 10) == []

    def test_single_value_1(self):
        assert parse_range("1", 5) == [1]

    def test_range_clipped_to_max(self):
        # 8-15 with max_val=10 -> [8, 9, 10]
        assert parse_range("8-15", 10) == [8, 9, 10]


# ── compute_indices ───────────────────────────────────────────────────────

class TestComputeIndices:
    def test_show_all(self):
        assert compute_indices(10, None, None, show_all=True) == list(range(1, 11))

    def test_with_range(self):
        assert compute_indices(10, None, "3-5", show_all=False) == [3, 4, 5]

    def test_with_n(self):
        # Last 3 of 10 -> [8, 9, 10]
        assert compute_indices(10, 3, None, show_all=False) == [8, 9, 10]

    def test_default(self):
        # Default shows last DEFAULT_TURNS
        result = compute_indices(20, None, None, show_all=False)
        assert result == list(range(20 - DEFAULT_TURNS + 1, 21))

    def test_small_total(self):
        # When total < DEFAULT_TURNS, show all
        result = compute_indices(3, None, None, show_all=False)
        assert result == [1, 2, 3]

    def test_n_larger_than_total(self):
        result = compute_indices(3, 10, None, show_all=False)
        assert result == [1, 2, 3]

    def test_empty(self):
        assert compute_indices(0, None, None, show_all=True) == []
