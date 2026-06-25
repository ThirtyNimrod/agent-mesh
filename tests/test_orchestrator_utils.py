"""
Unit tests for the orchestrator helper functions:
  parse_text, parse_points, parse_memory_id

These run entirely in-process — no servers or Ollama required.
"""
import pytest
from agent.orchestrator import parse_text, parse_points, parse_memory_id


# ---------------------------------------------------------------------------
# parse_text
# ---------------------------------------------------------------------------

class _Msg:
    """Minimal stand-in for a LangChain message or tool response."""
    def __init__(self, content):
        self.content = content


def test_parse_text_plain_string():
    assert parse_text(_Msg("hello world")) == "hello world"


def test_parse_text_json_with_text_key():
    assert parse_text(_Msg('{"text": "extracted content"}')) == "extracted content"


def test_parse_text_json_without_text_key_returns_raw():
    raw = '{"id": 1, "score": 0.9}'
    assert parse_text(_Msg(raw)) == raw


def test_parse_text_mcp_content_block_list():
    """langchain-mcp-adapters may return content as a list of typed blocks."""
    msg = _Msg([{"type": "text", "text": "from block"}])
    assert parse_text(msg) == "from block"


def test_parse_text_mcp_list_picks_first_text_block():
    msg = _Msg([
        {"type": "image", "data": "..."},
        {"type": "text", "text": "second block"},
    ])
    assert parse_text(msg) == "second block"


def test_parse_text_mcp_list_with_string_item():
    msg = _Msg(["plain string inside list"])
    assert parse_text(msg) == "plain string inside list"


def test_parse_text_empty_list_returns_empty():
    assert parse_text(_Msg([])) == ""


def test_parse_text_no_content_attr():
    assert parse_text("direct string") == "direct string"


# ---------------------------------------------------------------------------
# parse_points
# ---------------------------------------------------------------------------

def test_parse_points_valid_json_array():
    pts = parse_points('["fact one", "fact two", "fact three"]')
    assert pts == ["fact one", "fact two", "fact three"]


def test_parse_points_json_with_key_points_key():
    pts = parse_points('{"key_points": ["a", "b"]}')
    assert pts == ["a", "b"]


def test_parse_points_json_with_points_key():
    pts = parse_points('{"points": ["x", "y"]}')
    assert pts == ["x", "y"]


def test_parse_points_strips_markdown_code_fence():
    pts = parse_points('```json\n["a", "b"]\n```')
    assert pts == ["a", "b"]


def test_parse_points_strips_plain_code_fence():
    pts = parse_points('```\n["a", "b"]\n```')
    assert pts == ["a", "b"]


def test_parse_points_bullet_fallback():
    pts = parse_points("- first point\n- second point\n* third")
    assert len(pts) == 3
    assert "first point" in pts
    assert "third" in pts


def test_parse_points_empty_string_returns_empty():
    assert parse_points("") == []


def test_parse_points_strips_blank_lines_in_fallback():
    pts = parse_points("one\n\ntwo\n\nthree")
    assert len(pts) == 3


# ---------------------------------------------------------------------------
# parse_memory_id
# ---------------------------------------------------------------------------

def test_parse_memory_id_from_json_string():
    assert parse_memory_id(_Msg('{"id": 42, "created_at": "2026-01-01"}')) == 42


def test_parse_memory_id_from_mcp_content_block():
    msg = _Msg([{"type": "text", "text": '{"id": 7}'}])
    assert parse_memory_id(msg) == 7


def test_parse_memory_id_missing_key_returns_none():
    assert parse_memory_id(_Msg('{"error": "not found"}')) is None


def test_parse_memory_id_invalid_json_returns_none():
    assert parse_memory_id(_Msg("not json at all")) is None


def test_parse_memory_id_empty_returns_none():
    assert parse_memory_id(_Msg("")) is None
