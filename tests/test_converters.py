"""
Unit tests for the converter registry and each converter engine.
All tests run in-process — no servers or external tools required,
with the exception of the pandoc tests which are skipped when
pandoc is not installed.
"""
import pytest
from servers.converters import find, all_pairs, REGISTRY


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def test_all_pairs_not_empty():
    assert len(all_pairs()) > 0


def test_all_pairs_includes_markdown_to_text():
    assert ("markdown", "text") in all_pairs(), \
        "markdown->text must be supported without pandoc"


def test_all_pairs_includes_text_to_text():
    assert ("text", "text") in all_pairs()


def test_all_pairs_includes_markdown_to_markdown():
    assert ("markdown", "markdown") in all_pairs()


def test_find_returns_none_for_unknown_pair():
    assert find("foobar", "baz") is None


def test_find_is_case_sensitive():
    # Format names are lower-case; "Markdown" should not match
    assert find("Markdown", "text") is None


# ---------------------------------------------------------------------------
# Passthrough converter
# ---------------------------------------------------------------------------

def test_passthrough_text_to_text():
    c = find("text", "text")
    assert c is not None
    data = b"hello world"
    assert c.convert(data, "text", "text") == data


def test_passthrough_markdown_to_markdown():
    c = find("markdown", "markdown")
    assert c is not None
    data = b"# Title\n\nContent"
    assert c.convert(data, "markdown", "markdown") == data


def test_passthrough_preserves_binary_bytes():
    c = find("text", "text")
    data = bytes(range(128))
    assert c.convert(data, "text", "text") == data


# ---------------------------------------------------------------------------
# Markdown -> text  (must work WITHOUT pandoc)
# ---------------------------------------------------------------------------

SAMPLE_MD = b"""\
# Agent Mesh Architecture

The **agent-mesh** project uses _LangGraph_ for orchestration.

## Components

- `memory-server`: stores vectors via FAISS
- `file-bridge-server`: converts documents
- `prompt-audit-server`: tracks LLM call costs

[Read more](https://example.com)
"""


def test_markdown_to_text_converter_exists():
    assert find("markdown", "text") is not None, \
        "A converter for markdown->text must exist and not require pandoc"


def test_markdown_to_text_returns_bytes():
    c = find("markdown", "text")
    result = c.convert(SAMPLE_MD, "markdown", "text")
    assert isinstance(result, bytes)


def test_markdown_to_text_contains_key_words():
    c = find("markdown", "text")
    text = c.convert(SAMPLE_MD, "markdown", "text").decode("utf-8")
    assert "Agent Mesh Architecture" in text
    assert "LangGraph" in text
    assert "memory-server" in text


def test_markdown_to_text_strips_header_hashes():
    c = find("markdown", "text")
    text = c.convert(b"# My Title\n\nBody text.", "markdown", "text").decode()
    assert "My Title" in text
    assert "#" not in text


def test_markdown_to_text_strips_bold_markers():
    c = find("markdown", "text")
    text = c.convert(b"Some **bold** word.", "markdown", "text").decode()
    assert "bold" in text
    assert "**" not in text


def test_markdown_to_text_strips_link_syntax():
    c = find("markdown", "text")
    text = c.convert(b"[Click here](https://example.com)", "markdown", "text").decode()
    assert "Click here" in text
    assert "https://example.com" not in text


def test_markdown_to_text_strips_inline_code_backticks():
    c = find("markdown", "text")
    text = c.convert(b"Use `print()` to output.", "markdown", "text").decode()
    assert "print()" in text
    assert "`" not in text


def test_markdown_to_text_nonempty_for_nonempty_input():
    c = find("markdown", "text")
    result = c.convert(SAMPLE_MD, "markdown", "text")
    assert len(result) > 0


def test_markdown_to_text_empty_input_returns_empty():
    c = find("markdown", "text")
    result = c.convert(b"", "markdown", "text")
    assert result == b""


# ---------------------------------------------------------------------------
# Pandoc converter  (skipped if pandoc binary is absent)
# ---------------------------------------------------------------------------

def _pandoc_available() -> bool:
    try:
        import pypandoc
        pypandoc.get_pandoc_version()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _pandoc_available(), reason="pandoc not installed")
def test_pandoc_markdown_to_html():
    c = find("markdown", "html")
    assert c is not None
    result = c.convert(b"# Hello", "markdown", "html").decode()
    assert "<h1" in result.lower()


@pytest.mark.skipif(not _pandoc_available(), reason="pandoc not installed")
def test_pandoc_html_to_text():
    c = find("html", "text")
    assert c is not None
    result = c.convert(b"<p>Hello world</p>", "html", "text").decode()
    assert "Hello world" in result
