"""
Unit tests for SubagentManager continue_subagent functionality.

Tests for the subagent continuation feature:
- Registry lookup in own directory
- Cross-agent registry fallback
- Session ID retrieval
- Error handling for missing sessions
- Integration test for multi-turn conversation flow
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from massgen.subagent.manager import SubagentManager

# =============================================================================
# Registry Lookup Tests
# =============================================================================


class TestContinueSubagentRegistryLookup:
    """Tests for registry lookup when continuing subagents."""

    def _create_manager_with_temp_workspace(self) -> tuple[SubagentManager, Path]:
        """Create a manager with a temporary workspace."""
        tmp_dir = Path(tempfile.mkdtemp())
        workspace = tmp_dir / "workspace"
        workspace.mkdir(parents=True)

        manager = SubagentManager(
            parent_workspace=str(workspace),
            parent_agent_id="test-agent",
            orchestrator_id="test-orch",
            parent_agent_configs=[],
        )

        return manager, tmp_dir

    def _create_registry(
        self,
        registry_dir: Path,
        subagents: list[dict],
        parent_agent_id: str = "test-agent",
    ) -> Path:
        """Create a registry file with the given subagents."""
        registry_dir.mkdir(parents=True, exist_ok=True)
        registry_file = registry_dir / "_registry.json"

        registry_data = {
            "parent_agent_id": parent_agent_id,
            "orchestrator_id": "test-orch",
            "subagents": subagents,
        }
        registry_file.write_text(json.dumps(registry_data, indent=2))
        return registry_file

    @pytest.mark.asyncio
    async def test_lookup_in_own_registry(self):
        """Test that subagent is found in the manager's own registry."""
        manager, tmp_dir = self._create_manager_with_temp_workspace()

        try:
            # Create subagent workspace
            subagent_workspace = tmp_dir / "workspace" / "subagents" / "sub_001"
            subagent_workspace.mkdir(parents=True)

            # Set up registry in manager's subagents_base
            manager.subagents_base = tmp_dir / "workspace" / "subagents"

            # Create registry with a subagent entry
            self._create_registry(
                manager.subagents_base,
                subagents=[
                    {
                        "subagent_id": "sub_001",
                        "session_id": "session-abc-123",
                        "task": "Test task",
                        "status": "completed",
                        "workspace": str(subagent_workspace),
                        "created_at": "2025-01-01T00:00:00",
                        "success": True,
                    },
                ],
            )

            # Mock subprocess to avoid actual execution
            with patch("asyncio.create_subprocess_exec") as mock_exec:
                mock_process = AsyncMock()
                mock_process.returncode = 0
                mock_process.communicate = AsyncMock(return_value=(b"Test answer", b""))
                mock_exec.return_value = mock_process

                # Create answer file
                answer_file = subagent_workspace / "answer_continued.txt"
                answer_file.write_text("Continued response")

                result = await manager.continue_subagent(
                    subagent_id="sub_001",
                    new_message="Continue the task",
                )

                # Should find subagent and execute (even if process fails)
                # The key test is that it found the subagent and got session_id
                assert result.subagent_id == "sub_001"
                # If subprocess ran, it should use --session-id flag
                if mock_exec.called:
                    call_args = mock_exec.call_args[0]
                    assert "--session-id" in call_args
                    assert "session-abc-123" in call_args
        finally:
            import shutil

            shutil.rmtree(tmp_dir, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_cross_agent_registry_fallback(self):
        """Test fallback to other agent registries when not found in own registry."""
        manager, tmp_dir = self._create_manager_with_temp_workspace()

        try:
            # Set up empty own registry
            manager.subagents_base = tmp_dir / "workspace" / "subagents"
            self._create_registry(manager.subagents_base, subagents=[])

            # Set up agent_temporary_workspace with another agent's registry
            agent_temp_workspace = tmp_dir / "agent_temps"
            agent_temp_workspace.mkdir(parents=True)
            manager._agent_temporary_workspace = agent_temp_workspace

            # Create another agent's workspace with the target subagent
            other_agent_dir = agent_temp_workspace / "other-agent"
            other_agent_subagents = other_agent_dir / "subagents"
            other_subagent_workspace = other_agent_subagents / "sub_002"
            other_subagent_workspace.mkdir(parents=True)

            self._create_registry(
                other_agent_subagents,
                subagents=[
                    {
                        "subagent_id": "sub_002",
                        "session_id": "session-xyz-456",
                        "task": "Other agent's task",
                        "status": "completed",
                        "workspace": str(other_subagent_workspace),
                        "created_at": "2025-01-01T00:00:00",
                        "success": True,
                    },
                ],
                parent_agent_id="other-agent",
            )

            # Mock subprocess
            with patch("asyncio.create_subprocess_exec") as mock_exec:
                mock_process = AsyncMock()
                mock_process.returncode = 0
                mock_process.communicate = AsyncMock(return_value=(b"Answer", b""))
                mock_exec.return_value = mock_process

                # Create answer file
                answer_file = other_subagent_workspace / "answer_continued.txt"
                answer_file.write_text("Cross-agent response")

                result = await manager.continue_subagent(
                    subagent_id="sub_002",
                    new_message="Continue cross-agent task",
                )

                assert result.subagent_id == "sub_002"
                # Should have found the session_id from other agent's registry
                if mock_exec.called:
                    call_args = mock_exec.call_args[0]
                    assert "--session-id" in call_args
                    assert "session-xyz-456" in call_args
        finally:
            import shutil

            shutil.rmtree(tmp_dir, ignore_errors=True)


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestContinueSubagentErrorHandling:
    """Tests for error handling in continue_subagent."""

    @pytest.mark.asyncio
    async def test_error_when_subagent_not_found(self):
        """Test error returned when subagent ID not found in any registry."""
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            workspace = tmp_dir / "workspace"
            workspace.mkdir(parents=True)

            manager = SubagentManager(
                parent_workspace=str(workspace),
                parent_agent_id="test-agent",
                orchestrator_id="test-orch",
                parent_agent_configs=[],
            )

            # Empty registry
            manager.subagents_base = workspace / "subagents"
            manager.subagents_base.mkdir(parents=True, exist_ok=True)
            registry_file = manager.subagents_base / "_registry.json"
            registry_file.write_text(json.dumps({"subagents": []}))

            result = await manager.continue_subagent(
                subagent_id="nonexistent_subagent",
                new_message="Continue",
            )

            assert result.status == "error"
            assert result.success is False
            assert "not found in any registry" in result.error
        finally:
            import shutil

            shutil.rmtree(tmp_dir, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_error_when_no_session_id(self):
        """Test error returned when subagent has no session_id."""
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            workspace = tmp_dir / "workspace"
            workspace.mkdir(parents=True)

            manager = SubagentManager(
                parent_workspace=str(workspace),
                parent_agent_id="test-agent",
                orchestrator_id="test-orch",
                parent_agent_configs=[],
            )

            # Registry with subagent but no session_id
            manager.subagents_base = workspace / "subagents"
            manager.subagents_base.mkdir(parents=True, exist_ok=True)
            registry_file = manager.subagents_base / "_registry.json"
            registry_file.write_text(
                json.dumps(
                    {
                        "subagents": [
                            {
                                "subagent_id": "sub_no_session",
                                # No session_id field!
                                "task": "Test task",
                                "status": "completed",
                                "workspace": str(workspace / "sub_workspace"),
                            },
                        ],
                    },
                ),
            )

            result = await manager.continue_subagent(
                subagent_id="sub_no_session",
                new_message="Continue",
            )

            assert result.status == "error"
            assert result.success is False
            assert "no session_id" in result.error.lower()
        finally:
            import shutil

            shutil.rmtree(tmp_dir, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_error_when_workspace_missing(self):
        """Test error returned when workspace directory doesn't exist."""
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            workspace = tmp_dir / "workspace"
            workspace.mkdir(parents=True)

            manager = SubagentManager(
                parent_workspace=str(workspace),
                parent_agent_id="test-agent",
                orchestrator_id="test-orch",
                parent_agent_configs=[],
            )

            # Registry with subagent pointing to non-existent workspace
            manager.subagents_base = workspace / "subagents"
            manager.subagents_base.mkdir(parents=True, exist_ok=True)
            registry_file = manager.subagents_base / "_registry.json"
            registry_file.write_text(
                json.dumps(
                    {
                        "subagents": [
                            {
                                "subagent_id": "sub_missing_workspace",
                                "session_id": "session-123",
                                "task": "Test task",
                                "status": "completed",
                                "workspace": "/nonexistent/path/to/workspace",
                            },
                        ],
                    },
                ),
            )

            result = await manager.continue_subagent(
                subagent_id="sub_missing_workspace",
                new_message="Continue",
            )

            assert result.status == "error"
            assert result.success is False
            assert "workspace not found" in result.error.lower()
        finally:
            import shutil

            shutil.rmtree(tmp_dir, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_error_on_corrupted_registry(self):
        """Test graceful handling of corrupted registry JSON."""
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            workspace = tmp_dir / "workspace"
            workspace.mkdir(parents=True)

            manager = SubagentManager(
                parent_workspace=str(workspace),
                parent_agent_id="test-agent",
                orchestrator_id="test-orch",
                parent_agent_configs=[],
            )

            # Corrupted registry file
            manager.subagents_base = workspace / "subagents"
            manager.subagents_base.mkdir(parents=True, exist_ok=True)
            registry_file = manager.subagents_base / "_registry.json"
            registry_file.write_text("{ invalid json }")

            result = await manager.continue_subagent(
                subagent_id="any_subagent",
                new_message="Continue",
            )

            # Should not crash, should return error
            assert result.status == "error"
            assert result.success is False
        finally:
            import shutil

            shutil.rmtree(tmp_dir, ignore_errors=True)


# =============================================================================
# Session ID Retrieval Tests
# =============================================================================


class TestContinueSubagentSessionRetrieval:
    """Tests for session ID retrieval from registry."""

    @pytest.mark.asyncio
    async def test_session_id_used_in_command(self):
        """Test that session_id is correctly passed to subprocess command."""
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            workspace = tmp_dir / "workspace"
            workspace.mkdir(parents=True)
            subagent_workspace = workspace / "subagents" / "sub_test"
            subagent_workspace.mkdir(parents=True)

            manager = SubagentManager(
                parent_workspace=str(workspace),
                parent_agent_id="test-agent",
                orchestrator_id="test-orch",
                parent_agent_configs=[],
            )

            manager.subagents_base = workspace / "subagents"
            registry_file = manager.subagents_base / "_registry.json"
            registry_file.write_text(
                json.dumps(
                    {
                        "subagents": [
                            {
                                "subagent_id": "sub_test",
                                "session_id": "unique-session-id-12345",
                                "task": "Test task",
                                "status": "completed",
                                "workspace": str(subagent_workspace),
                            },
                        ],
                    },
                ),
            )

            # Create answer file
            answer_file = subagent_workspace / "answer_continued.txt"
            answer_file.write_text("Test response")

            with patch("asyncio.create_subprocess_exec") as mock_exec:
                mock_process = AsyncMock()
                mock_process.returncode = 0
                mock_process.communicate = AsyncMock(return_value=(b"output", b""))
                mock_exec.return_value = mock_process

                await manager.continue_subagent(
                    subagent_id="sub_test",
                    new_message="New message",
                )

                # Verify command includes --session-id with correct value
                call_args = mock_exec.call_args[0]
                args_list = list(call_args)

                session_id_idx = args_list.index("--session-id")
                assert args_list[session_id_idx + 1] == "unique-session-id-12345"

                # Verify new message is included
                assert "New message" in args_list
        finally:
            import shutil

            shutil.rmtree(tmp_dir, ignore_errors=True)


# =============================================================================
# Process Execution Tests
# =============================================================================


class TestContinueSubagentExecution:
    """Tests for subprocess execution in continue_subagent."""

    @pytest.mark.asyncio
    async def test_timeout_handling(self):
        """Test that timeout is properly handled during continuation."""
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            workspace = tmp_dir / "workspace"
            workspace.mkdir(parents=True)
            subagent_workspace = workspace / "subagents" / "sub_timeout"
            subagent_workspace.mkdir(parents=True)

            manager = SubagentManager(
                parent_workspace=str(workspace),
                parent_agent_id="test-agent",
                orchestrator_id="test-orch",
                parent_agent_configs=[],
                min_timeout=1,  # Allow short timeout for testing
            )

            manager.subagents_base = workspace / "subagents"
            registry_file = manager.subagents_base / "_registry.json"
            registry_file.write_text(
                json.dumps(
                    {
                        "subagents": [
                            {
                                "subagent_id": "sub_timeout",
                                "session_id": "session-timeout",
                                "task": "Long task",
                                "status": "running",
                                "workspace": str(subagent_workspace),
                            },
                        ],
                    },
                ),
            )

            with patch("asyncio.create_subprocess_exec") as mock_exec:
                mock_process = AsyncMock()
                mock_process.terminate = MagicMock()
                mock_process.kill = MagicMock()
                mock_process.wait = AsyncMock()

                # Simulate timeout
                mock_process.communicate = AsyncMock(
                    side_effect=TimeoutError("Process timed out"),
                )
                mock_exec.return_value = mock_process

                # Patch asyncio.wait_for to raise TimeoutError
                __import__("asyncio").wait_for

                async def mock_wait_for(coro, timeout):
                    raise __import__("asyncio").TimeoutError()

                with patch("asyncio.wait_for", side_effect=mock_wait_for):
                    result = await manager.continue_subagent(
                        subagent_id="sub_timeout",
                        new_message="Continue",
                        timeout_seconds=1,
                    )

                # Should return error with timeout message
                assert result.status == "error"
                assert "timed out" in result.error.lower()
                # Process should be terminated
                mock_process.terminate.assert_called_once()
        finally:
            import shutil

            shutil.rmtree(tmp_dir, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_successful_continuation(self):
        """Test successful continuation returns proper result."""
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            workspace = tmp_dir / "workspace"
            workspace.mkdir(parents=True)
            subagent_workspace = workspace / "subagents" / "sub_success"
            subagent_workspace.mkdir(parents=True)

            manager = SubagentManager(
                parent_workspace=str(workspace),
                parent_agent_id="test-agent",
                orchestrator_id="test-orch",
                parent_agent_configs=[],
            )

            manager.subagents_base = workspace / "subagents"
            registry_file = manager.subagents_base / "_registry.json"
            registry_file.write_text(
                json.dumps(
                    {
                        "subagents": [
                            {
                                "subagent_id": "sub_success",
                                "session_id": "session-success",
                                "task": "Test task",
                                "status": "completed",
                                "workspace": str(subagent_workspace),
                            },
                        ],
                    },
                ),
            )

            # Create answer file
            answer_file = subagent_workspace / "answer_continued.txt"
            answer_file.write_text("The continued answer from subagent")

            with patch("asyncio.create_subprocess_exec") as mock_exec:
                mock_process = AsyncMock()
                mock_process.returncode = 0
                mock_process.communicate = AsyncMock(return_value=(b"", b""))
                mock_exec.return_value = mock_process

                result = await manager.continue_subagent(
                    subagent_id="sub_success",
                    new_message="Follow-up question",
                )

                assert result.status == "completed"
                assert result.success is True
                assert result.answer == "The continued answer from subagent"
                assert result.workspace_path == str(subagent_workspace)
        finally:
            import shutil

            shutil.rmtree(tmp_dir, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_registry_updated_after_continuation(self):
        """Test that registry is updated after successful continuation."""
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            workspace = tmp_dir / "workspace"
            workspace.mkdir(parents=True)
            subagent_workspace = workspace / "subagents" / "sub_update"
            subagent_workspace.mkdir(parents=True)

            manager = SubagentManager(
                parent_workspace=str(workspace),
                parent_agent_id="test-agent",
                orchestrator_id="test-orch",
                parent_agent_configs=[],
            )

            manager.subagents_base = workspace / "subagents"
            registry_file = manager.subagents_base / "_registry.json"
            registry_file.write_text(
                json.dumps(
                    {
                        "subagents": [
                            {
                                "subagent_id": "sub_update",
                                "session_id": "session-update",
                                "task": "Test task",
                                "status": "running",  # Initial status
                                "workspace": str(subagent_workspace),
                            },
                        ],
                    },
                ),
            )

            # Create answer file
            answer_file = subagent_workspace / "answer_continued.txt"
            answer_file.write_text("Updated answer")

            with patch("asyncio.create_subprocess_exec") as mock_exec:
                mock_process = AsyncMock()
                mock_process.returncode = 0
                mock_process.communicate = AsyncMock(return_value=(b"", b""))
                mock_exec.return_value = mock_process

                await manager.continue_subagent(
                    subagent_id="sub_update",
                    new_message="Continue",
                )

            # Check registry was updated
            updated_registry = json.loads(registry_file.read_text())
            subagent_entry = updated_registry["subagents"][0]

            assert subagent_entry["status"] == "completed"
            assert "last_continued_at" in subagent_entry
        finally:
            import shutil

            shutil.rmtree(tmp_dir, ignore_errors=True)
