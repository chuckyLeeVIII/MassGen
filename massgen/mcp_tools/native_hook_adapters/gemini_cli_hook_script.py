#!/usr/bin/env python3
"""Gemini CLI hook script — standalone subprocess invoked by Gemini CLI.

This script is called by Gemini CLI as a subprocess for BeforeTool/AfterTool
hook events. It reads JSON from stdin (the hook event), checks for a payload
file written by the MassGen orchestrator, and returns a JSON response on stdout.

IMPORTANT: This script must NOT import from massgen — it runs as an isolated
subprocess in the Gemini CLI process, potentially inside Docker where massgen
is not installed. All logic must be self-contained.

Usage (configured in .gemini/settings.json):
    python3 gemini_cli_hook_script.py --hook-dir /path/to/.gemini --event AfterTool

Hook event JSON (stdin):
    {"toolName": "read_file", "toolArgs": {"path": "foo.txt"}, "toolResult": "..."}

Response JSON (stdout):
    {} — allow without modifications
    {"additionalContext": "..."} — inject content after tool result
    {"decision": "deny", "reason": "..."} — deny the tool call (BeforeTool only)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="MassGen hook script for Gemini CLI")
    parser.add_argument("--hook-dir", required=True, help="Directory containing hook payload files")
    parser.add_argument("--event", required=True, choices=["BeforeTool", "AfterTool"], help="Hook event type")
    args = parser.parse_args()

    hook_dir = Path(args.hook_dir)
    event = args.event

    # Read hook event from stdin
    try:
        stdin_data = sys.stdin.read()
        if stdin_data.strip():
            json.loads(stdin_data)
        else:
            pass
    except (json.JSONDecodeError, OSError):
        pass

    # Check for payload file
    payload_file = hook_dir / "hook_payload.json"
    try:
        if not payload_file.exists():
            _emit({})
            return

        payload_text = payload_file.read_text(encoding="utf-8")
        payload = json.loads(payload_text)

        # Check expiration
        expires_at = payload.get("expires_at", 0)
        if expires_at and time.time() > expires_at:
            # Expired — clean up and allow
            payload_file.unlink(missing_ok=True)
            _emit({})
            return

        # Check event match
        payload_event = payload.get("event", "AfterTool")
        if payload_event != event:
            # Wrong event type — don't consume, pass through
            _emit({})
            return

        # Consume the payload (delete after reading)
        payload_file.unlink(missing_ok=True)

        # Extract injection content
        inject = payload.get("inject", {})
        content = inject.get("content", "")

        if not content:
            _emit({})
            return

        if event == "AfterTool":
            _emit({"additionalContext": content})
        elif event == "BeforeTool":
            # BeforeTool can inject context or deny
            strategy = inject.get("strategy", "tool_result")
            if strategy == "deny":
                _emit({"decision": "deny", "reason": content})
            else:
                _emit({"additionalContext": content})

    except (json.JSONDecodeError, OSError):
        # On any error, allow the tool call to proceed
        _emit({})


def _emit(response: dict) -> None:
    """Write JSON response to stdout."""
    json.dump(response, sys.stdout)
    sys.stdout.write("\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
