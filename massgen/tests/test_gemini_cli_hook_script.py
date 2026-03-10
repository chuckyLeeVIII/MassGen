"""Tests for the standalone Gemini CLI hook script (subprocess).

The hook script runs as a subprocess invoked by Gemini CLI. It reads a
payload file written by the MassGen orchestrator and returns JSON on stdout.
These tests invoke it directly as a subprocess to verify end-to-end behavior.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

HOOK_SCRIPT = str(
    Path(__file__).parent.parent / "mcp_tools" / "native_hook_adapters" / "gemini_cli_hook_script.py",
)


def _run_hook_script(
    hook_dir: str,
    event: str,
    stdin_data: str = "{}",
) -> dict:
    """Invoke the hook script as a subprocess and return parsed JSON output."""
    result = subprocess.run(
        [sys.executable, HOOK_SCRIPT, "--hook-dir", hook_dir, "--event", event],
        input=stdin_data,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, f"Hook script failed: {result.stderr}"
    output = result.stdout.strip()
    if not output:
        return {}
    return json.loads(output)


class TestHookScriptNoPayload:
    """When no payload file exists, hook script should return empty dict (allow)."""

    def test_returns_empty_for_after_tool(self, tmp_path: Path) -> None:
        result = _run_hook_script(str(tmp_path), "AfterTool")
        assert result == {}

    def test_returns_empty_for_before_tool(self, tmp_path: Path) -> None:
        result = _run_hook_script(str(tmp_path), "BeforeTool")
        assert result == {}

    def test_handles_empty_stdin(self, tmp_path: Path) -> None:
        result = _run_hook_script(str(tmp_path), "AfterTool", stdin_data="")
        assert result == {}


class TestHookScriptAfterToolInjection:
    """AfterTool event with a valid payload should inject additionalContext."""

    def _write_payload(self, hook_dir: Path, content: str, event: str = "AfterTool") -> None:
        hook_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "inject": {"content": content, "strategy": "tool_result"},
            "event": event,
            "expires_at": time.time() + 30,
            "sequence": 1,
        }
        (hook_dir / "hook_payload.json").write_text(json.dumps(payload))

    def test_injects_additional_context(self, tmp_path: Path) -> None:
        self._write_payload(tmp_path, "Agent B answered: 42")
        result = _run_hook_script(str(tmp_path), "AfterTool")
        assert result == {"additionalContext": "Agent B answered: 42"}

    def test_consumes_payload_file(self, tmp_path: Path) -> None:
        """After consumption, the payload file should be deleted."""
        self._write_payload(tmp_path, "content")
        _run_hook_script(str(tmp_path), "AfterTool")
        assert not (tmp_path / "hook_payload.json").exists()

    def test_second_invocation_returns_empty(self, tmp_path: Path) -> None:
        """Payload is single-use — second invocation should return empty."""
        self._write_payload(tmp_path, "one-shot content")
        first = _run_hook_script(str(tmp_path), "AfterTool")
        assert "additionalContext" in first

        second = _run_hook_script(str(tmp_path), "AfterTool")
        assert second == {}

    def test_large_content(self, tmp_path: Path) -> None:
        """Hook should handle large injection content."""
        large_content = "x" * 100_000
        self._write_payload(tmp_path, large_content)
        result = _run_hook_script(str(tmp_path), "AfterTool")
        assert result["additionalContext"] == large_content


class TestHookScriptBeforeToolInjection:
    """BeforeTool event with a valid payload should inject or deny."""

    def _write_payload(
        self,
        hook_dir: Path,
        content: str,
        strategy: str = "tool_result",
    ) -> None:
        hook_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "inject": {"content": content, "strategy": strategy},
            "event": "BeforeTool",
            "expires_at": time.time() + 30,
            "sequence": 1,
        }
        (hook_dir / "hook_payload.json").write_text(json.dumps(payload))

    def test_injects_context_with_tool_result_strategy(self, tmp_path: Path) -> None:
        self._write_payload(tmp_path, "context injection", strategy="tool_result")
        result = _run_hook_script(str(tmp_path), "BeforeTool")
        assert result == {"additionalContext": "context injection"}

    def test_deny_with_deny_strategy(self, tmp_path: Path) -> None:
        self._write_payload(tmp_path, "Permission denied: read-only path", strategy="deny")
        result = _run_hook_script(str(tmp_path), "BeforeTool")
        assert result["decision"] == "deny"
        assert "Permission denied" in result["reason"]


class TestHookScriptExpiry:
    """Expired payloads should be cleaned up and treated as no-op."""

    def test_expired_payload_returns_empty(self, tmp_path: Path) -> None:
        tmp_path.mkdir(parents=True, exist_ok=True)
        payload = {
            "inject": {"content": "should not appear", "strategy": "tool_result"},
            "event": "AfterTool",
            "expires_at": time.time() - 10,  # Expired 10 seconds ago
            "sequence": 1,
        }
        (tmp_path / "hook_payload.json").write_text(json.dumps(payload))

        result = _run_hook_script(str(tmp_path), "AfterTool")
        assert result == {}

    def test_expired_payload_cleans_up_file(self, tmp_path: Path) -> None:
        tmp_path.mkdir(parents=True, exist_ok=True)
        payload = {
            "inject": {"content": "expired", "strategy": "tool_result"},
            "event": "AfterTool",
            "expires_at": time.time() - 1,
            "sequence": 1,
        }
        (tmp_path / "hook_payload.json").write_text(json.dumps(payload))

        _run_hook_script(str(tmp_path), "AfterTool")
        assert not (tmp_path / "hook_payload.json").exists()


class TestHookScriptEventMismatch:
    """Payloads for wrong event type should be ignored (not consumed)."""

    def test_after_tool_payload_not_consumed_by_before_tool(self, tmp_path: Path) -> None:
        tmp_path.mkdir(parents=True, exist_ok=True)
        payload = {
            "inject": {"content": "for AfterTool", "strategy": "tool_result"},
            "event": "AfterTool",
            "expires_at": time.time() + 30,
            "sequence": 1,
        }
        (tmp_path / "hook_payload.json").write_text(json.dumps(payload))

        result = _run_hook_script(str(tmp_path), "BeforeTool")
        assert result == {}
        # File should NOT be consumed — it's for a different event
        assert (tmp_path / "hook_payload.json").exists()

    def test_before_tool_payload_not_consumed_by_after_tool(self, tmp_path: Path) -> None:
        tmp_path.mkdir(parents=True, exist_ok=True)
        payload = {
            "inject": {"content": "for BeforeTool", "strategy": "deny"},
            "event": "BeforeTool",
            "expires_at": time.time() + 30,
            "sequence": 1,
        }
        (tmp_path / "hook_payload.json").write_text(json.dumps(payload))

        result = _run_hook_script(str(tmp_path), "AfterTool")
        assert result == {}
        assert (tmp_path / "hook_payload.json").exists()


class TestHookScriptMalformedPayload:
    """Malformed payload files should not crash the hook — just allow."""

    def test_invalid_json_returns_empty(self, tmp_path: Path) -> None:
        tmp_path.mkdir(parents=True, exist_ok=True)
        (tmp_path / "hook_payload.json").write_text("not valid json {{")

        result = _run_hook_script(str(tmp_path), "AfterTool")
        assert result == {}

    def test_empty_file_returns_empty(self, tmp_path: Path) -> None:
        tmp_path.mkdir(parents=True, exist_ok=True)
        (tmp_path / "hook_payload.json").write_text("")

        result = _run_hook_script(str(tmp_path), "AfterTool")
        assert result == {}

    def test_missing_inject_key_returns_empty(self, tmp_path: Path) -> None:
        tmp_path.mkdir(parents=True, exist_ok=True)
        (tmp_path / "hook_payload.json").write_text(json.dumps({"event": "AfterTool"}))

        result = _run_hook_script(str(tmp_path), "AfterTool")
        assert result == {}


class TestHookScriptStdinHandling:
    """Hook script should handle various stdin formats gracefully."""

    def test_valid_tool_event_on_stdin(self, tmp_path: Path) -> None:
        """Real Gemini CLI sends tool event data on stdin."""
        stdin = json.dumps(
            {
                "toolName": "read_file",
                "toolArgs": {"path": "test.txt"},
                "toolResult": "file contents",
            },
        )
        result = _run_hook_script(str(tmp_path), "AfterTool", stdin_data=stdin)
        assert result == {}

    def test_invalid_json_stdin_doesnt_crash(self, tmp_path: Path) -> None:
        result = _run_hook_script(str(tmp_path), "AfterTool", stdin_data="broken {json")
        assert result == {}
