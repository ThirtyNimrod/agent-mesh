import pytest
from pathlib import Path
from common.config import settings
import servers.file_bridge_server as server
import servers.converters as conv

def test_safe_path(tmp_path, monkeypatch):
    root_dir = str(tmp_path / "files")
    monkeypatch.setattr(settings(), "files_dir", root_dir)
    
    # Path inside files_dir sandbox should resolve correctly
    resolved = server._safe_path("test.txt")
    assert str(resolved).startswith(root_dir)
    
    # Nested folder path should resolve
    resolved_nested = server._safe_path("sub/nested.txt")
    assert str(resolved_nested).startswith(root_dir)
    
    # Traversal attempt escaping sandbox should raise ValueError
    with pytest.raises(ValueError, match="path escapes allowed directory"):
        server._safe_path("../escaped.txt")

def test_passthrough_converter():
    passthrough = conv.find("text", "text")
    assert passthrough is not None
    assert passthrough.name == "passthrough"
    
    data = b"Hello, File Bridge!"
    converted = passthrough.convert(data, "text", "text")
    assert converted == data

def test_list_formats():
    pairs = conv.all_pairs()
    # Check that basic pairs are present
    assert ("txt", "text") in pairs
    assert ("markdown", "html") in pairs
    assert ("pdf", "text") in pairs
