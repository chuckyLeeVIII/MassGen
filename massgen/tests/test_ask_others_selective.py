"""
Unit tests for ask_others selective broadcast mode (agent_prompts parameter).

Tests for the selective broadcast functionality:
- Parameter parsing for agent_prompts
- Filtering to only specified agents
- Per-agent prompts being used
- Validation of agent IDs
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from massgen.tool.workflow_toolkits.broadcast import BroadcastToolkit

# =============================================================================
# Selective Broadcast Parameter Tests
# =============================================================================


class TestSelectiveBroadcastParameters:
    """Tests for agent_prompts parameter in ask_others tool."""

    def test_agent_prompts_parameter_defined(self):
        """Test that agent_prompts parameter is properly defined."""
        toolkit = BroadcastToolkit(broadcast_mode="agents")
        tools = toolkit.get_tools({"api_format": "claude"})

        ask_others = [t for t in tools if t.get("name") == "ask_others"][0]
        props = ask_others["input_schema"]["properties"]

        assert "agent_prompts" in props
        assert props["agent_prompts"]["type"] == "object"
        assert "additionalProperties" in props["agent_prompts"]
        assert props["agent_prompts"]["additionalProperties"]["type"] == "string"

    def test_agent_prompts_description(self):
        """Test that agent_prompts has a helpful description."""
        toolkit = BroadcastToolkit(broadcast_mode="agents")
        tools = toolkit.get_tools({"api_format": "chat_completions"})

        ask_others = [t for t in tools if t.get("function", {}).get("name") == "ask_others"][0]
        props = ask_others["function"]["parameters"]["properties"]

        assert "selective broadcast" in props["agent_prompts"]["description"].lower()


# =============================================================================
# Selective Broadcast Routing Tests
# =============================================================================


class TestSelectiveBroadcastRouting:
    """Tests for routing to selective broadcast mode."""

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
            return_value={
                "status": "completed",
                "responses": [
                    {"responder_id": "shadow_Agent-2", "content": "Agent-2's response"},
                ],
            },
        )
        return orchestrator

    @pytest.mark.asyncio
    async def test_agent_prompts_routes_to_selective_broadcast(self):
        """Test that agent_prompts triggers selective broadcast mode."""
        orchestrator = self._create_mock_orchestrator()
        toolkit = BroadcastToolkit(orchestrator=orchestrator, broadcast_mode="agents")

        arguments = json.dumps(
            {
                "agent_prompts": {
                    "Agent-2": "Review my API design",
                    "Agent-3": "Check for security issues",
                },
            },
        )

        result = await toolkit._execute_ask_others_impl(arguments, "Agent-1")
        result_data = json.loads(result)

        assert result_data["status"] == "completed"
        assert "target_agents" in result_data
        assert set(result_data["target_agents"]) == {"Agent-2", "Agent-3"}

        # Verify broadcast channel was called with target_agents
        orchestrator.broadcast_channel.inject_into_agents.assert_called_once()
        call_args = orchestrator.broadcast_channel.inject_into_agents.call_args
        assert set(call_args.kwargs["target_agents"]) == {"Agent-2", "Agent-3"}

    @pytest.mark.asyncio
    async def test_agent_prompts_passed_to_inject(self):
        """Test that agent_prompts dict is passed to inject_into_agents."""
        orchestrator = self._create_mock_orchestrator()
        toolkit = BroadcastToolkit(orchestrator=orchestrator, broadcast_mode="agents")

        agent_prompts = {
            "Agent-2": "Specific question for Agent-2",
            "Agent-3": "Specific question for Agent-3",
        }
        arguments = json.dumps({"agent_prompts": agent_prompts})

        await toolkit._execute_ask_others_impl(arguments, "Agent-1")

        call_args = orchestrator.broadcast_channel.inject_into_agents.call_args
        assert call_args.kwargs["agent_prompts"] == agent_prompts

    @pytest.mark.asyncio
    async def test_empty_agent_prompts_uses_broadcast_all(self):
        """Test that empty agent_prompts falls back to broadcast all."""
        orchestrator = self._create_mock_orchestrator()
        orchestrator.broadcast_channel.wait_for_responses = AsyncMock(
            return_value={"status": "completed", "responses": []},
        )

        toolkit = BroadcastToolkit(orchestrator=orchestrator, broadcast_mode="agents")

        # Empty dict should fall back to broadcast all
        arguments = json.dumps(
            {
                "agent_prompts": {},
                "question": "General question to all",
            },
        )

        await toolkit._execute_ask_others_impl(arguments, "Agent-1")

        # Should NOT have target_agents in the call (broadcast to all)
        call_args = orchestrator.broadcast_channel.inject_into_agents.call_args
        # For broadcast all, target_agents should be None or not passed
        assert call_args is None or call_args.kwargs.get("target_agents") is None


# =============================================================================
# Validation Tests
# =============================================================================


class TestSelectiveBroadcastValidation:
    """Tests for validation in selective broadcast mode."""

    def _create_mock_orchestrator(self) -> MagicMock:
        """Create a mock orchestrator."""
        orchestrator = MagicMock()
        orchestrator.agents = {
            "Agent-1": MagicMock(),
            "Agent-2": MagicMock(),
        }
        orchestrator.config.coordination_config.broadcast = "agents"
        orchestrator.config.coordination_config.broadcast_timeout = 30
        return orchestrator

    @pytest.mark.asyncio
    async def test_error_when_agent_not_found(self):
        """Test error when agent_prompts contains invalid agent ID."""
        orchestrator = self._create_mock_orchestrator()
        toolkit = BroadcastToolkit(orchestrator=orchestrator, broadcast_mode="agents")

        arguments = json.dumps(
            {
                "agent_prompts": {
                    "Agent-2": "Valid agent",
                    "NonexistentAgent": "Invalid agent",
                },
            },
        )

        result = await toolkit._execute_ask_others_impl(arguments, "Agent-1")
        result_data = json.loads(result)

        assert result_data["status"] == "error"
        assert "NonexistentAgent" in result_data["error"]
        assert "Invalid agent IDs" in result_data["error"]

    @pytest.mark.asyncio
    async def test_self_filtered_from_targets(self):
        """Test that asking agent is filtered out from targets."""
        orchestrator = self._create_mock_orchestrator()
        orchestrator.broadcast_channel = MagicMock()
        orchestrator.broadcast_channel.create_broadcast = AsyncMock(return_value="req-123")
        orchestrator.broadcast_channel.inject_into_agents = AsyncMock()
        orchestrator.broadcast_channel.wait_for_responses = AsyncMock(
            return_value={"status": "completed", "responses": []},
        )

        toolkit = BroadcastToolkit(orchestrator=orchestrator, broadcast_mode="agents")

        # Try to include self in agent_prompts
        arguments = json.dumps(
            {
                "agent_prompts": {
                    "Agent-1": "Question to myself (should be filtered)",
                    "Agent-2": "Valid target",
                },
            },
        )

        result = await toolkit._execute_ask_others_impl(arguments, "Agent-1")
        result_data = json.loads(result)

        # Agent-1 should be filtered out
        assert "Agent-2" in result_data.get("target_agents", [])
        assert "Agent-1" not in result_data.get("target_agents", [])

    @pytest.mark.asyncio
    async def test_error_when_only_self_in_targets(self):
        """Test error when only the asking agent is in targets."""
        orchestrator = self._create_mock_orchestrator()
        toolkit = BroadcastToolkit(orchestrator=orchestrator, broadcast_mode="agents")

        # Only self in targets
        arguments = json.dumps(
            {
                "agent_prompts": {
                    "Agent-1": "Question to myself only",
                },
            },
        )

        result = await toolkit._execute_ask_others_impl(arguments, "Agent-1")
        result_data = json.loads(result)

        assert result_data["status"] == "error"
        assert "no valid target agents" in result_data["error"].lower()


# =============================================================================
# Broadcast Channel Integration Tests
# =============================================================================


class TestBroadcastChannelSelectiveSupport:
    """Tests for selective broadcast support in BroadcastChannel."""

    @pytest.mark.asyncio
    async def test_create_broadcast_accepts_target_agents(self):
        """Test that create_broadcast accepts target_agents parameter."""
        from massgen._broadcast_channel import BroadcastChannel

        orchestrator = MagicMock()
        orchestrator.agents = {
            "Agent-1": MagicMock(),
            "Agent-2": MagicMock(),
            "Agent-3": MagicMock(),
        }
        orchestrator.config.coordination_config.max_broadcasts_per_agent = 5
        orchestrator.config.coordination_config.broadcast_timeout = 30
        orchestrator.config.coordination_config.broadcast = "agents"

        channel = BroadcastChannel(orchestrator)

        # Should accept target_agents parameter
        request_id = await channel.create_broadcast(
            sender_agent_id="Agent-1",
            question="Test question",
            target_agents=["Agent-2"],  # Only Agent-2
        )

        assert request_id is not None
        broadcast = channel.active_broadcasts[request_id]
        # Expected response count should be 1 (only Agent-2)
        assert broadcast.expected_response_count == 1

    @pytest.mark.asyncio
    async def test_inject_into_agents_accepts_parameters(self):
        """Test that inject_into_agents accepts selective parameters."""
        from massgen._broadcast_channel import BroadcastChannel

        orchestrator = MagicMock()
        orchestrator.agents = {
            "Agent-1": MagicMock(),
            "Agent-2": MagicMock(),
            "Agent-3": MagicMock(),
        }
        orchestrator.config.coordination_config.max_broadcasts_per_agent = 5
        orchestrator.config.coordination_config.broadcast_timeout = 30
        orchestrator.config.coordination_config.broadcast = "agents"

        channel = BroadcastChannel(orchestrator)

        # Create a broadcast
        request_id = await channel.create_broadcast(
            sender_agent_id="Agent-1",
            question="Test question",
        )

        # Mock _spawn_shadow_agents to verify parameters are passed
        with patch.object(channel, "_spawn_shadow_agents", new=AsyncMock()) as mock_spawn:
            await channel.inject_into_agents(
                request_id,
                target_agents=["Agent-2", "Agent-3"],
                agent_prompts={"Agent-2": "Q1", "Agent-3": "Q2"},
            )

            mock_spawn.assert_called_once_with(
                request_id,
                target_agents=["Agent-2", "Agent-3"],
                agent_prompts={"Agent-2": "Q1", "Agent-3": "Q2"},
            )


# =============================================================================
# Human Mode Tests
# =============================================================================


class TestSelectiveBroadcastHumanMode:
    """Tests to verify selective broadcast is ignored in human mode."""

    @pytest.mark.asyncio
    async def test_human_mode_ignores_agent_prompts(self):
        """Test that human mode ignores agent_prompts and uses normal flow."""
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

        # Provide agent_prompts which should be ignored in human mode
        arguments = json.dumps(
            {
                "agent_prompts": {"Agent-2": "Ignored question"},
                "question": "Question for human",
            },
        )

        result = await toolkit._execute_ask_others_impl(arguments, "Agent-1")
        result_data = json.loads(result)

        # Should follow human mode flow
        assert result_data["status"] == "completed"
        assert "target_agents" not in result_data
        # Broadcast channel should be called for human mode
        orchestrator.broadcast_channel.create_broadcast.assert_called_once()
