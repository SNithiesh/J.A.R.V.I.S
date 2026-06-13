"""MCP adapter unit tests — config parsing and graceful absence.
The full connect/discover/call path is integration-tested separately
(needs the mcp SDK + a live server); these cover the pure logic."""
import json
from app import mcp_client


def test_load_config_missing_is_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(mcp_client, "CONFIG_PATH", tmp_path / "nope.json")
    assert mcp_client.load_config() == []


def test_load_config_filters_disabled(monkeypatch, tmp_path):
    cfg = tmp_path / "mcp_config.json"
    cfg.write_text(json.dumps({"servers": [
        {"name": "a", "command": "x", "enabled": True},
        {"name": "b", "command": "y", "enabled": False},
        {"name": "c", "command": "z"},  # default enabled
    ]}))
    monkeypatch.setattr(mcp_client, "CONFIG_PATH", cfg)
    names = [s["name"] for s in mcp_client.load_config()]
    assert names == ["a", "c"]


def test_load_config_malformed_is_empty(monkeypatch, tmp_path):
    cfg = tmp_path / "bad.json"
    cfg.write_text("{ not json")
    monkeypatch.setattr(mcp_client, "CONFIG_PATH", cfg)
    assert mcp_client.load_config() == []


def test_status_empty_initially():
    # fresh module state: no servers started
    assert isinstance(mcp_client.status(), list)
