"""
Unit tests for ask_others targeted mode (target_agent_id parameter).

Tests for the targeted ask functionality:
- Parameter parsing and mode detection
- Mode priority (target_agent_id takes precedence over agent_prompts)
- Validation of target agent existence
- Error handling for missing execution traces
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from massgen.tool.workflow_toolkits.broadcast import BroadcastToolkit

# =============================================================================
# Tool Parameter Tests
# =============================================================================


class TestAskOthersToolParameters:
    """Tests for ask_others tool parameter definitions."""

    def test_agents_mode_includes_target_agent_id(self):
        """Test that agents mode includes target_agent_id parameter."""
        toolkit = BroadcastToolkit(broadcast_mode="agents")
        tools = toolkit.get_tools({"api_format": "claude"})

        ask_others = [t for t in tools if t.get("name") == "ask_others"][0]
        props = ask_others["input_schema"]["properties"]

        assert "target_agent_id" in props
        assert props["target_agent_id"]["type"] == "string"
        assert "subagent" in props["target_agent_id"]["description"].lower()

    def test_agents_mode_includes_enable_tools(self):
        """Test that agents mode includes enable_tools parameter."""
        toolkit = BroadcastToolkit(broadcast_mode="agents")
        tools = toolkit.get_tools({"api_format": "claude"})

        ask_others = [t for t in tools if t.get("name") == "ask_others"][0]
        props = ask_others["input_schema"]["properties"]

        assert "enable_tools" in props
        assert props["enable_tools"]["type"] == "boolean"

    def test_agents_mode_includes_agent_prompts(self):
        """Test that agents mode includes agent_prompts parameter."""
        toolkit = BroadcastToolkit(broadcast_mode="agents")
        tools = toolkit.get_tools({"api_format": "claude"})

        ask_others = [t for t in tools if t.get("name") == "ask_others"][0]
        props = ask_others["input_schema"]["properties"]

        assert "agent_prompts" in props
        assert props["agent_prompts"]["type"] == "object"

    def test_human_mode_excludes_new_parameters(self):
        """Test that human mode excludes the new agent-only parameters."""
        toolkit = BroadcastToolkit(broadcast_mode="human")
        tools = toolkit.get_tools({"api_format": "claude"})

        ask_others = [t for t in tools if t.get("name") == "ask_others"][0]
        props = ask_others["input_schema"]["properties"]

        assert "target_agent_id" not in props
        assert "enable_tools" not in props
        assert "agent_prompts" not in props

    def test_chat_completions_format_includes_parameters(self):
        """Test that chat completions format also includes the new parameters."""
        toolkit = BroadcastToolkit(broadcast_mode="agents")
        tools = toolkit.get_tools({"api_format": "chat_completions"})

        ask_others = [t for t in tools if t.get("function", {}).get("name") == "ask_others"][0]
        props = ask_others["function"]["parameters"]["properties"]

        assert "target_agent_id" in props
        assert "enable_tools" in props
        assert "agent_prompts" in props


# =============================================================================
# Mode Detection Tests
# =============================================================================


class TestAskOthersModeDetection:
    """Tests for mode detection in _execute_ask_others_impl."""

    def _create_mock_orchestrator(self) -> MagicMock:
        """Create a mock orchestrator with necessary attributes."""
        orchestrator = MagicMock()
        orchestrator.agents = {
            "Agent-1": MagicMock(),
            "Agent-2": MagicMock(),
            "Agent-3": MagicMock(),
        }
        orchestrator.config.coordination_config.broadcast_timeout = 30
        orchestrator.config.coordination_config.broadcast = "agents"
        orchestrator.broadcast_channel = MagicMock()
        orchestrator.broadcast_channel.create_broadcast = AsyncMock(return_value="request-123")
        orchestrator.broadcast_channel.inject_into_agents = AsyncMock()
        orchestrator.broadcast_channel.wait_for_responses = AsyncMock(
            return_value={"status": "completed", "responses": []},
        )
        return orchestrator

    @pytest.mark.asyncio
    async def test_target_agent_id_routes_to_targeted_ask(self):
        """Test that target_agent_id parameter triggers targeted ask mode."""
        orchestrator = self._create_mock_orchestrator()
        orchestrator.get_latest_execution_trace = MagicMock(
            return_value="# Execution trace content",
        )
        orchestrator.get_agent_backend_config = MagicMock(return_value={"model": "gpt-4"})

        # Mock the subagent manager
        subagent_manager = MagicMock()
        mock_result = MagicMock()
        mock_result.status = "completed"
        mock_result.success = True
        mock_result.answer = "Test answer"
        mock_result.subagent_id = "sub_123"
        mock_result.execution_time_seconds = 1.5
        subagent_manager.spawn_subagent = AsyncMock(return_value=mock_result)
        orchestrator.agents["Agent-1"].backend.subagent_manager = subagent_manager

        toolkit = BroadcastToolkit(orchestrator=orchestrator, broadcast_mode="agents")

        arguments = json.dumps(
            {
                "target_agent_id": "Agent-2",
                "question": "Why did you choose this approach?",
            },
        )

        result = await toolkit._execute_ask_others_impl(arguments, "Agent-1")
        result_data = json.loads(result)

        # Verify targeted ask was called
        assert result_data["target_agent_id"] == "Agent-2"
        assert result_data["subagent_id"] == "sub_123"
        assert result_data["answer"] == "Test answer"
        assert "continue_subagent_hint" in result_data

        # Verify broadcast was NOT called
        orchestrator.broadcast_channel.create_broadcast.assert_not_called()

    @pytest.mark.asyncio
    async def test_target_agent_id_takes_priority_over_agent_prompts(self):
        """Test that target_agent_id takes precedence when both are provided."""
        orchestrator = self._create_mock_orchestrator()
        orchestrator.get_latest_execution_trace = MagicMock(
            return_value="# Execution trace content",
        )
        orchestrator.get_agent_backend_config = MagicMock(return_value={"model": "gpt-4"})

        subagent_manager = MagicMock()
        mock_result = MagicMock()
        mock_result.status = "completed"
        mock_result.success = True
        mock_result.answer = "Targeted answer"
        mock_result.subagent_id = "sub_456"
        mock_result.execution_time_seconds = 1.0
        subagent_manager.spawn_subagent = AsyncMock(return_value=mock_result)
        orchestrator.agents["Agent-1"].backend.subagent_manager = subagent_manager

        toolkit = BroadcastToolkit(orchestrator=orchestrator, broadcast_mode="agents")

        # Provide both target_agent_id and agent_prompts
        arguments = json.dumps(
            {
                "target_agent_id": "Agent-2",
                "agent_prompts": {"Agent-3": "Different question"},
                "question": "Main question",
            },
        )

        result = await toolkit._execute_ask_others_impl(arguments, "Agent-1")
        result_data = json.loads(result)

        # Should use targeted mode, not selective broadcast
        assert result_data["target_agent_id"] == "Agent-2"
        assert "subagent_id" in result_data


# =============================================================================
# Validation Tests
# =============================================================================


class TestTargetedAskValidation:
    """Tests for validation in targeted ask mode."""

    def _create_mock_orchestrator(self) -> MagicMock:
        """Create a mock orchestrator."""
        orchestrator = MagicMock()
        orchestrator.agents = {
            "Agent-1": MagicMock(),
            "Agent-2": MagicMock(),
        }
        orchestrator.config.coordination_config.broadcast = "agents"
        return orchestrator

    @pytest.mark.asyncio
    async def test_error_when_target_agent_not_found(self):
        """Test error returned when target_agent_id doesn't exist."""
        orchestrator = self._create_mock_orchestrator()
        toolkit = BroadcastToolkit(orchestrator=orchestrator, broadcast_mode="agents")

        arguments = json.dumps(
            {
                "target_agent_id": "NonexistentAgent",
                "question": "Test question",
            },
        )

        result = await toolkit._execute_ask_others_impl(arguments, "Agent-1")
        result_data = json.loads(result)

        assert result_data["status"] == "error"
        assert "NonexistentAgent" in result_data["error"]
        assert "not found" in result_data["error"].lower()

    @pytest.mark.asyncio
    async def test_error_when_no_execution_trace(self):
        """Test error returned when target agent has no execution trace."""
        orchestrator = self._create_mock_orchestrator()
        orchestrator.get_latest_execution_trace = MagicMock(return_value=None)

        toolkit = BroadcastToolkit(orchestrator=orchestrator, broadcast_mode="agents")

        arguments = json.dumps(
            {
                "target_agent_id": "Agent-2",
                "question": "Test question",
            },
        )

        result = await toolkit._execute_ask_others_impl(arguments, "Agent-1")
        result_data = json.loads(result)

        assert result_data["status"] == "error"
        assert "execution trace" in result_data["error"].lower()

    @pytest.mark.asyncio
    async def test_error_when_no_subagent_manager(self):
        """Test error returned when SubagentManager is not available."""
        orchestrator = self._create_mock_orchestrator()
        orchestrator.get_latest_execution_trace = MagicMock(
            return_value="# Execution trace",
        )
        # No subagent_manager attribute
        orchestrator.agents["Agent-1"].backend = MagicMock(spec=[])

        toolkit = BroadcastToolkit(orchestrator=orchestrator, broadcast_mode="agents")

        arguments = json.dumps(
            {
                "target_agent_id": "Agent-2",
                "question": "Test question",
            },
        )

        result = await toolkit._execute_ask_others_impl(arguments, "Agent-1")
        result_data = json.loads(result)

        assert result_data["status"] == "error"
        assert "SubagentManager" in result_data["error"]


# =============================================================================
# Human Mode Tests
# =============================================================================


class TestTargetedAskHumanMode:
    """Tests to verify targeted ask is ignored in human mode."""

    @pytest.mark.asyncio
    async def test_human_mode_ignores_target_agent_id(self):
        """Test that human mode ignores target_agent_id and uses normal flow."""
        orchestrator = MagicMock()
        orchestrator.agents = {
            "Agent-1": MagicMock(),
            "Agent-2": MagicMock(),
        }
        orchestrator.config.coordination_config.broadcast = "human"
        orchestrator.config.coordination_config.broadcast_timeout = 30
        orchestrator.broadcast_channel = MagicMock()
        orchestrator.broadcast_channel.get_human_qa_history = MagicMock(return_value=[])
        orchestrator.broadcast_channel.create_broadcast = AsyncMock(return_value="req-123")
        orchestrator.broadcast_channel.inject_into_agents = AsyncMock()
        orchestrator.broadcast_channel.wait_for_responses = AsyncMock(
            return_value={"status": "completed", "responses": [{"answer": "human response"}]},
        )

        toolkit = BroadcastToolkit(orchestrator=orchestrator, broadcast_mode="human")

        # Provide target_agent_id which should be ignored in human mode
        arguments = json.dumps(
            {
                "target_agent_id": "Agent-2",
                "question": "Should I use React or Vue?",
            },
        )

        result = await toolkit._execute_ask_others_impl(arguments, "Agent-1")
        result_data = json.loads(result)

        # Should follow human mode flow, not targeted ask
        assert result_data["status"] == "completed"
        assert "subagent_id" not in result_data
        # Broadcast channel should be called for human mode
        orchestrator.broadcast_channel.create_broadcast.assert_called_once()
