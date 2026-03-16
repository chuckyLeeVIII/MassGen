"""
Tests for the fix to OpenAI Responses API duplicate item errors.

When using previous_response_id for reasoning model continuity (GPT-5, o3, o4),
the recursive tool-execution loop in response.py must only send NEW items
(function_call_output) in the input, not the full conversation history.
The server-side response chain already includes all prior context via
previous_response_id. Sending the full history causes:
  400 - Duplicate item found with id rs_XXXX

Bug: https://github.com/Leezekun/MassGen/issues/XXX
"""


class TestPrepareRecursiveMessages:
    """Unit tests for _prepare_recursive_messages helper."""

    def _make_backend(self):
        """Create a minimal ResponseBackend-like object with the helper."""
        # Import here to avoid import-time side effects
        from massgen.backend.response import ResponseBackend

        # We only need the static helper; avoid full __init__
        # by calling the method unbound on a dummy namespace.
        return ResponseBackend

    # ------------------------------------------------------------------
    # Core filtering behaviour
    # ------------------------------------------------------------------

    def test_filters_to_new_items_when_previous_response_id_set(self):
        """When previous_response_id is used, only items added after
        new_items_start_index should be returned."""
        cls = self._make_backend()

        original_messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
            {"type": "reasoning", "id": "rs_abc123", "content": []},
            {
                "type": "function_call",
                "id": "fc_1",
                "call_id": "call_1",
                "name": "read_file",
                "arguments": "{}",
            },
        ]
        new_items = [
            {
                "type": "function_call_output",
                "call_id": "call_1",
                "output": "file contents",
            },
        ]
        all_messages = original_messages + new_items

        result = cls._prepare_recursive_messages(
            all_messages,
            new_items_start_index=len(original_messages),
            has_previous_response_id=True,
        )

        assert result == new_items
        # No reasoning items should remain
        assert not any(m.get("id", "").startswith("rs_") for m in result)

    def test_keeps_full_messages_when_no_previous_response_id(self):
        """Without previous_response_id the full (trimmed) history
        must be returned."""
        cls = self._make_backend()

        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
            {
                "type": "function_call_output",
                "call_id": "c1",
                "output": "ok",
            },
        ]

        result = cls._prepare_recursive_messages(
            messages,
            new_items_start_index=2,
            has_previous_response_id=False,
        )

        # Full list returned (trimming is the caller's responsibility)
        assert result == messages

    def test_multiple_new_items_preserved(self):
        """All items after new_items_start_index are kept when
        previous_response_id is used, including error outputs."""
        cls = self._make_backend()

        original = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "q"},
        ]
        new_items = [
            {
                "type": "function_call_output",
                "call_id": "c1",
                "output": "result 1",
            },
            {
                "type": "function_call_output",
                "call_id": "c2",
                "output": "Error: tool not processed",
            },
        ]
        all_msgs = original + new_items

        result = cls._prepare_recursive_messages(
            all_msgs,
            new_items_start_index=len(original),
            has_previous_response_id=True,
        )

        assert len(result) == 2
        assert result[0]["call_id"] == "c1"
        assert result[1]["call_id"] == "c2"

    def test_no_reasoning_items_leak_with_previous_response_id(self):
        """Reasoning items from prior responses must not appear in the
        filtered input when previous_response_id is active."""
        cls = self._make_backend()

        messages = [
            {"role": "system", "content": "sys"},
            {"type": "reasoning", "id": "rs_first", "content": []},
            {
                "type": "function_call",
                "id": "fc_1",
                "call_id": "c1",
                "name": "tool",
                "arguments": "{}",
            },
            {
                "type": "function_call_output",
                "call_id": "c1",
                "output": "ok",
            },
            # Items from a second response also accumulated
            {"type": "reasoning", "id": "rs_second", "content": []},
            {
                "type": "function_call",
                "id": "fc_2",
                "call_id": "c2",
                "name": "tool2",
                "arguments": "{}",
            },
            # new_items_start_index would be here (6)
            {
                "type": "function_call_output",
                "call_id": "c2",
                "output": "ok2",
            },
        ]

        result = cls._prepare_recursive_messages(
            messages,
            new_items_start_index=6,
            has_previous_response_id=True,
        )

        assert len(result) == 1
        assert result[0]["call_id"] == "c2"

    def test_empty_new_items_with_previous_response_id(self):
        """Edge case: if no new items were added but previous_response_id
        is set, return empty list (shouldn't normally happen but must
        not crash)."""
        cls = self._make_backend()

        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
        ]

        result = cls._prepare_recursive_messages(
            messages,
            new_items_start_index=len(messages),
            has_previous_response_id=True,
        )

        assert result == []


class TestRecursiveCallIntegration:
    """Integration-level tests verifying the recursive flow sends
    correct input when previous_response_id is active.

    These tests verify the logic by directly testing the
    _prepare_recursive_messages helper and the index tracking
    that feeds into it, matching the real code path.
    """

    def test_simulated_recursive_flow_filters_correctly(self):
        """Simulate the full recursive flow logic and verify that
        when previous_response_id would be set, only new items
        (function_call_output) end up in the recursive call input.

        This replicates the exact sequence in
        _stream_with_custom_and_mcp_tools without needing to mock
        the full streaming pipeline.
        """
        from massgen.backend.response import ResponseBackend

        # --- Simulate iteration 1 state ---
        current_messages = [
            {"role": "system", "content": "You are a helper."},
            {"role": "user", "content": "Read test.txt"},
        ]

        # Step 1: copy + mark boundary (matches line 580-581)
        updated_messages = current_messages.copy()
        new_items_start_index = len(updated_messages)

        # Step 2: response_output_items NOT added because
        # will_use_previous_response_id=True (matches line 598)
        # (listed here for documentation; not appended to updated_messages)
        _response_output_items = [  # noqa: F841
            {"type": "reasoning", "id": "rs_test_001", "content": []},
            {
                "type": "function_call",
                "id": "fc_test_001",
                "call_id": "call_001",
                "name": "read_file",
                "arguments": "{}",
            },
        ]
        # Skipped (will_use_previous_response_id=True)

        # Step 3: tool execution appends function_call_output
        updated_messages.append(
            {
                "type": "function_call_output",
                "call_id": "call_001",
                "output": "file contents here",
            },
        )

        # Step 4: prepare for recursive call
        response_id = "resp_001"
        has_prev = bool(response_id)  # True

        result = ResponseBackend._prepare_recursive_messages(
            updated_messages,
            new_items_start_index=new_items_start_index,
            has_previous_response_id=has_prev,
        )

        # Only the function_call_output should remain
        assert len(result) == 1
        assert result[0]["type"] == "function_call_output"
        assert result[0]["call_id"] == "call_001"

        # No system/user messages
        assert not any(m.get("role") == "system" for m in result)
        assert not any(m.get("role") == "user" for m in result)

        # No reasoning items
        assert not any(m.get("id", "").startswith("rs_") for m in result)

    def test_simulated_flow_keeps_full_history_without_response_id(self):
        """When response_id is None (first call), the full message
        list must be preserved for the recursive call."""
        from massgen.backend.response import ResponseBackend

        current_messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
        ]

        updated_messages = current_messages.copy()
        new_items_start_index = len(updated_messages)

        # response_output_items added because no previous_response_id
        updated_messages.extend(
            [
                {"type": "reasoning", "id": "rs_001", "content": []},
                {
                    "type": "function_call",
                    "id": "fc_001",
                    "call_id": "c1",
                    "name": "tool",
                    "arguments": "{}",
                },
            ],
        )

        # Tool output added
        updated_messages.append(
            {
                "type": "function_call_output",
                "call_id": "c1",
                "output": "ok",
            },
        )

        result = ResponseBackend._prepare_recursive_messages(
            updated_messages,
            new_items_start_index=new_items_start_index,
            has_previous_response_id=False,
        )

        # Full list returned
        assert len(result) == 5
        assert result[0]["role"] == "system"

    def test_simulated_multi_tool_call_iteration(self):
        """Simulate multiple tool calls in one iteration — all their
        function_call_output items should appear in the filtered
        recursive input."""
        from massgen.backend.response import ResponseBackend

        current_messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "do things"},
        ]

        updated_messages = current_messages.copy()
        new_items_start_index = len(updated_messages)

        # Three tool outputs from parallel tool execution
        for i in range(3):
            updated_messages.append(
                {
                    "type": "function_call_output",
                    "call_id": f"call_{i}",
                    "output": f"result_{i}",
                },
            )

        result = ResponseBackend._prepare_recursive_messages(
            updated_messages,
            new_items_start_index=new_items_start_index,
            has_previous_response_id=True,
        )

        assert len(result) == 3
        assert all(r["type"] == "function_call_output" for r in result)
        call_ids = {r["call_id"] for r in result}
        assert call_ids == {"call_0", "call_1", "call_2"}
