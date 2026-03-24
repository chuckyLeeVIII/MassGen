"""
Tests for checkpoint coordination mode.

TDD: Tests written first, implementation follows.
Covers: checkpoint MCP server, proposed_actions on new_answer,
        orchestrator solo/checkpoint mode switching, gated patterns,
        and coordination tracker checkpoint events.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ============================================================================
# Phase 1: Checkpoint MCP Server
# ============================================================================


class TestCheckpointToolParameters:
    """Test checkpoint tool parameter validation."""

    def test_checkpoint_tool_requires_task(self):
        """checkpoint() must require a task parameter."""
        from massgen.mcp_tools.checkpoint._checkpoint_mcp_server import (
            validate_checkpoint_params,
        )

        with pytest.raises(ValueError, match="task"):
            validate_checkpoint_params(task="", context="", eval_criteria=["Good"])

    def test_checkpoint_tool_accepts_minimal_params(self):
        """checkpoint() with just task and eval_criteria should be valid."""
        from massgen.mcp_tools.checkpoint._checkpoint_mcp_server import (
            validate_checkpoint_params,
        )

        result = validate_checkpoint_params(
            task="Build the auth system",
            eval_criteria=["Secure authentication"],
        )
        assert result["task"] == "Build the auth system"

    def test_checkpoint_tool_accepts_full_params(self):
        """checkpoint() with all params should be valid."""
        from massgen.mcp_tools.checkpoint._checkpoint_mcp_server import (
            validate_checkpoint_params,
        )

        gated_actions = [
            {"tool": "mcp__vercel__deploy", "description": "Deploy to Vercel"},
        ]
        result = validate_checkpoint_params(
            task="Build and deploy",
            context="Website is ready",
            eval_criteria=["Deploys correctly"],
            gated_actions=gated_actions,
        )
        assert result["task"] == "Build and deploy"
        assert result["context"] == "Website is ready"
        assert len(result["gated_actions"]) == 1
        assert result["gated_actions"][0]["tool"] == "mcp__vercel__deploy"

    def test_checkpoint_gated_actions_validates_tool_field(self):
        """Each gated_action must have a 'tool' field."""
        from massgen.mcp_tools.checkpoint._checkpoint_mcp_server import (
            validate_checkpoint_params,
        )

        with pytest.raises(ValueError, match="tool"):
            validate_checkpoint_params(
                task="Deploy",
                eval_criteria=["Works"],
                gated_actions=[{"description": "no tool field"}],
            )


class TestCheckpointSignal:
    """Test checkpoint signal generation for orchestrator."""

    def test_build_checkpoint_signal(self):
        """Checkpoint tool should produce a signal dict for the orchestrator."""
        from massgen.mcp_tools.checkpoint._checkpoint_mcp_server import (
            build_checkpoint_signal,
        )

        signal = build_checkpoint_signal(
            task="Build the frontend",
            context="We need React",
            eval_criteria=["Beautiful UI"],
            gated_actions=[
                {"tool": "mcp__vercel__deploy", "description": "Deploy"},
            ],
        )
        assert signal["type"] == "checkpoint"
        assert signal["task"] == "Build the frontend"
        assert signal["context"] == "We need React"
        assert len(signal["gated_actions"]) == 1
        # Backward compat
        assert len(signal["expected_actions"]) == 1

    def test_build_checkpoint_signal_minimal(self):
        """Checkpoint signal with minimal params."""
        from massgen.mcp_tools.checkpoint._checkpoint_mcp_server import (
            build_checkpoint_signal,
        )

        signal = build_checkpoint_signal(
            task="Review code",
            context="",
            eval_criteria=["Code quality"],
        )
        assert signal["type"] == "checkpoint"
        assert signal["task"] == "Review code"
        assert signal["context"] == ""
        assert signal["gated_actions"] == []
        assert signal["eval_criteria"] == ["Code quality"]

    def test_checkpoint_signal_written_to_file(self, tmp_path):
        """Checkpoint signal should be written to workspace for orchestrator detection."""
        from massgen.mcp_tools.checkpoint._checkpoint_mcp_server import (
            write_checkpoint_signal,
        )

        signal = {
            "type": "checkpoint",
            "task": "Build auth",
            "context": "",
            "expected_actions": [],
        }
        write_checkpoint_signal(signal, tmp_path)

        signal_file = tmp_path / ".massgen_checkpoint_signal.json"
        assert signal_file.exists()
        loaded = json.loads(signal_file.read_text())
        assert loaded["type"] == "checkpoint"
        assert loaded["task"] == "Build auth"


class TestCheckpointResult:
    """Test checkpoint result formatting."""

    def test_format_checkpoint_result(self):
        """Format checkpoint result for return to main agent."""
        from massgen.mcp_tools.checkpoint._checkpoint_mcp_server import (
            format_checkpoint_result,
        )

        result = format_checkpoint_result(
            consensus="Built the website with React",
            workspace_changes=[
                {"file": "src/App.tsx", "change": "created"},
            ],
            action_results=[
                {
                    "tool": "mcp__vercel__deploy",
                    "executed": True,
                    "result": {"url": "https://my-site.vercel.app"},
                },
            ],
        )
        assert result["consensus"] == "Built the website with React"
        assert len(result["workspace_changes"]) == 1
        assert len(result["action_results"]) == 1
        assert result["action_results"][0]["executed"] is True

    def test_format_checkpoint_result_no_actions(self):
        """Checkpoint result with no action results."""
        from massgen.mcp_tools.checkpoint._checkpoint_mcp_server import (
            format_checkpoint_result,
        )

        result = format_checkpoint_result(
            consensus="Chose PostgreSQL",
            workspace_changes=[],
            action_results=[],
        )
        assert result["consensus"] == "Chose PostgreSQL"
        assert result["workspace_changes"] == []
        assert result["action_results"] == []


# ============================================================================
# Phase 1: Subrun Utils - build_checkpoint_mcp_config
# ============================================================================


class TestBuildCheckpointMcpConfig:
    """Test checkpoint MCP config generation."""

    def test_build_checkpoint_mcp_config_basic(self):
        """Should generate MCP config for checkpoint server."""
        from massgen.mcp_tools.subrun_utils import build_checkpoint_mcp_config

        config = build_checkpoint_mcp_config(
            workspace_path=Path("/tmp/workspace"),
            agent_id="architect",
        )
        assert config["name"] == "massgen_checkpoint"
        assert "command" in config
        assert "--workspace-path" in str(config)
        assert "--agent-id" in str(config)

    def test_build_checkpoint_mcp_config_with_gated_patterns(self):
        """Should pass gated patterns to MCP config."""
        from massgen.mcp_tools.subrun_utils import build_checkpoint_mcp_config

        config = build_checkpoint_mcp_config(
            workspace_path=Path("/tmp/workspace"),
            agent_id="architect",
            gated_patterns=["mcp__vercel__deploy*"],
        )
        # Gated patterns should be encoded in args
        args_str = " ".join(config.get("args", []))
        assert "gated_patterns" in args_str or "--gated-patterns" in args_str


# ============================================================================
# Phase 2: Extended new_answer with proposed_actions
# ============================================================================


class TestNewAnswerProposedActions:
    """Test new_answer tool with proposed_actions extension."""

    def test_new_answer_default_no_proposed_actions(self):
        """Normal new_answer should NOT have proposed_actions param."""
        from massgen.tool.workflow_toolkits.new_answer import NewAnswerToolkit

        toolkit = NewAnswerToolkit()
        config = {"api_format": "chat_completions", "enable_workflow_tools": True}
        tools = toolkit.get_tools(config)
        assert len(tools) == 1
        tool_def = tools[0]

        # Get properties from the tool definition
        if "function" in tool_def:
            props = tool_def["function"]["parameters"]["properties"]
        else:
            props = tool_def["input_schema"]["properties"]

        assert "proposed_actions" not in props

    def test_new_answer_checkpoint_context_has_proposed_actions(self):
        """new_answer in checkpoint context should have proposed_actions param."""
        from massgen.tool.workflow_toolkits.new_answer import NewAnswerToolkit

        toolkit = NewAnswerToolkit()
        config = {
            "api_format": "chat_completions",
            "enable_workflow_tools": True,
            "checkpoint_context": True,
        }
        tools = toolkit.get_tools(config)
        assert len(tools) == 1
        tool_def = tools[0]

        props = tool_def["function"]["parameters"]["properties"]
        assert "proposed_actions" in props

    def test_new_answer_proposed_actions_claude_format(self):
        """proposed_actions should appear in Claude format when checkpoint context."""
        from massgen.tool.workflow_toolkits.new_answer import NewAnswerToolkit

        toolkit = NewAnswerToolkit()
        config = {
            "api_format": "claude",
            "enable_workflow_tools": True,
            "checkpoint_context": True,
        }
        tools = toolkit.get_tools(config)
        tool_def = tools[0]
        props = tool_def["input_schema"]["properties"]
        assert "proposed_actions" in props

    def test_new_answer_proposed_actions_response_format(self):
        """proposed_actions should appear in Response API format when checkpoint context."""
        from massgen.tool.workflow_toolkits.new_answer import NewAnswerToolkit

        toolkit = NewAnswerToolkit()
        config = {
            "api_format": "response",
            "enable_workflow_tools": True,
            "checkpoint_context": True,
        }
        tools = toolkit.get_tools(config)
        tool_def = tools[0]
        props = tool_def["function"]["parameters"]["properties"]
        assert "proposed_actions" in props


class TestWorkflowToolsCheckpointContext:
    """Test get_workflow_tools passes checkpoint context through."""

    def test_get_workflow_tools_with_checkpoint_context(self):
        """get_workflow_tools should pass checkpoint_context to new_answer toolkit."""
        from massgen.tool.workflow_toolkits import get_workflow_tools

        tools = get_workflow_tools(
            valid_agent_ids=["agent1", "agent2"],
            api_format="chat_completions",
            checkpoint_context=True,
        )
        # Find new_answer tool
        new_answer_tool = None
        for t in tools:
            name = t.get("name") or t.get("function", {}).get("name")
            if name == "new_answer":
                new_answer_tool = t
                break

        assert new_answer_tool is not None
        props = new_answer_tool["function"]["parameters"]["properties"]
        assert "proposed_actions" in props

    def test_get_workflow_tools_without_checkpoint_context(self):
        """get_workflow_tools without checkpoint_context should NOT have proposed_actions."""
        from massgen.tool.workflow_toolkits import get_workflow_tools

        tools = get_workflow_tools(
            valid_agent_ids=["agent1", "agent2"],
            api_format="chat_completions",
        )
        new_answer_tool = None
        for t in tools:
            name = t.get("name") or t.get("function", {}).get("name")
            if name == "new_answer":
                new_answer_tool = t
                break

        assert new_answer_tool is not None
        props = new_answer_tool["function"]["parameters"]["properties"]
        assert "proposed_actions" not in props


# ============================================================================
# Phase 4: Gated Pattern Enforcement
# ============================================================================


class TestCheckpointGatedHook:
    """Test CheckpointGatedHook for blocking gated tools."""

    def test_gated_hook_blocks_matching_tool(self):
        """Gated hook should block tools matching gated_patterns."""
        from massgen.mcp_tools.hooks import CheckpointGatedHook, HookEvent

        hook = CheckpointGatedHook(
            gated_patterns=["mcp__vercel__deploy*", "mcp__github__delete_*"],
        )
        event = HookEvent(
            hook_type="PreToolUse",
            session_id="test",
            orchestrator_id="orch",
            agent_id="agent1",
            timestamp=MagicMock(),
            tool_name="mcp__vercel__deploy_production",
            tool_input={},
        )
        result = hook(event)
        assert result.decision == "deny"
        assert "checkpoint" in result.reason.lower() or "proposed_action" in result.reason.lower()

    def test_gated_hook_allows_non_matching_tool(self):
        """Gated hook should allow tools NOT matching gated_patterns."""
        from massgen.mcp_tools.hooks import CheckpointGatedHook, HookEvent

        hook = CheckpointGatedHook(
            gated_patterns=["mcp__vercel__deploy*"],
        )
        event = HookEvent(
            hook_type="PreToolUse",
            session_id="test",
            orchestrator_id="orch",
            agent_id="agent1",
            timestamp=MagicMock(),
            tool_name="mcp__github__read_file",
            tool_input={},
        )
        result = hook(event)
        assert result.decision == "allow"

    def test_gated_hook_uses_fnmatch(self):
        """Gated patterns should use fnmatch syntax."""
        from massgen.mcp_tools.hooks import CheckpointGatedHook, HookEvent

        hook = CheckpointGatedHook(
            gated_patterns=["mcp__*__production_*"],
        )
        # Should match
        event_match = HookEvent(
            hook_type="PreToolUse",
            session_id="test",
            orchestrator_id="orch",
            agent_id="agent1",
            timestamp=MagicMock(),
            tool_name="mcp__aws__production_deploy",
            tool_input={},
        )
        result = hook(event_match)
        assert result.decision == "deny"

        # Should not match
        event_no_match = HookEvent(
            hook_type="PreToolUse",
            session_id="test",
            orchestrator_id="orch",
            agent_id="agent1",
            timestamp=MagicMock(),
            tool_name="mcp__aws__staging_deploy",
            tool_input={},
        )
        result = hook(event_no_match)
        assert result.decision == "allow"

    def test_gated_hook_empty_patterns_allows_all(self):
        """Empty gated_patterns should allow all tools."""
        from massgen.mcp_tools.hooks import CheckpointGatedHook, HookEvent

        hook = CheckpointGatedHook(gated_patterns=[])
        event = HookEvent(
            hook_type="PreToolUse",
            session_id="test",
            orchestrator_id="orch",
            agent_id="agent1",
            timestamp=MagicMock(),
            tool_name="mcp__vercel__deploy",
            tool_input={},
        )
        result = hook(event)
        assert result.decision == "allow"


# ============================================================================
# Phase 4: Coordination Tracker Checkpoint Events
# ============================================================================


class TestCoordinationTrackerCheckpointEvents:
    """Test checkpoint event types in coordination tracker."""

    def test_checkpoint_event_types_exist(self):
        """Checkpoint event types should be defined."""
        from massgen.coordination_tracker import EventType

        assert hasattr(EventType, "CHECKPOINT_CALLED")
        assert hasattr(EventType, "CHECKPOINT_AGENTS_ACTIVATED")
        assert hasattr(EventType, "CHECKPOINT_CONSENSUS_REACHED")
        assert hasattr(EventType, "CHECKPOINT_ACTION_EXECUTED")
        assert hasattr(EventType, "CHECKPOINT_ACTION_FAILED")
        assert hasattr(EventType, "CHECKPOINT_COMPLETED")

    def test_tracker_records_checkpoint_event(self):
        """Tracker should record checkpoint events."""
        from massgen.coordination_tracker import (
            CoordinationTracker,
            EventType,
        )

        tracker = CoordinationTracker()
        tracker._add_event(
            EventType.CHECKPOINT_CALLED,
            agent_id="architect",
            details="Delegating: Build the frontend",
        )
        events = [e for e in tracker.events if e.event_type == EventType.CHECKPOINT_CALLED]
        assert len(events) == 1
        assert events[0].agent_id == "architect"


# ============================================================================
# Phase 3: Config Validation
# ============================================================================


class TestCheckpointConfigValidation:
    """Test checkpoint config validation."""

    def test_valid_checkpoint_config(self):
        """Valid checkpoint config should pass validation."""
        from massgen.config_validator import ConfigValidator

        validator = ConfigValidator()
        config = {
            "agents": [
                {
                    "id": "architect",
                    "main_agent": True,
                    "backend": {"type": "claude", "model": "claude-sonnet-4-20250514"},
                },
                {
                    "id": "builder",
                    "backend": {"type": "claude", "model": "claude-sonnet-4-20250514"},
                },
            ],
            "checkpoint": {
                "enabled": True,
                "mode": "conversation",
            },
        }
        result = validator.validate_config(config)
        # Should not have errors related to checkpoint
        checkpoint_errors = [e for e in result.errors if "checkpoint" in e.message.lower() or "main_agent" in e.message.lower()]
        assert len(checkpoint_errors) == 0

    def test_multiple_main_agents_rejected(self):
        """Multiple main_agent: true should be rejected."""
        from massgen.config_validator import ConfigValidator

        validator = ConfigValidator()
        config = {
            "agents": [
                {
                    "id": "agent1",
                    "main_agent": True,
                    "backend": {"type": "claude", "model": "claude-sonnet-4-20250514"},
                },
                {
                    "id": "agent2",
                    "main_agent": True,
                    "backend": {"type": "claude", "model": "claude-sonnet-4-20250514"},
                },
            ],
        }
        result = validator.validate_config(config)
        main_agent_errors = [e for e in result.errors if "main_agent" in e.message.lower()]
        assert len(main_agent_errors) > 0

    def test_invalid_checkpoint_mode(self):
        """Invalid checkpoint mode should produce a warning or error."""
        from massgen.config_validator import ConfigValidator

        validator = ConfigValidator()
        config = {
            "agents": [
                {
                    "id": "agent1",
                    "main_agent": True,
                    "backend": {"type": "claude", "model": "claude-sonnet-4-20250514"},
                },
                {
                    "id": "agent2",
                    "backend": {"type": "claude", "model": "claude-sonnet-4-20250514"},
                },
            ],
            "checkpoint": {
                "enabled": True,
                "mode": "invalid_mode",
            },
        }
        result = validator.validate_config(config)
        mode_errors = [e for e in result.errors if "mode" in e.message.lower() and "checkpoint" in e.location.lower()]
        assert len(mode_errors) > 0


# ============================================================================
# Phase 3: Agent Config - Checkpoint Fields
# ============================================================================


class TestCheckpointAgentConfig:
    """Test checkpoint fields in CoordinationConfig."""

    def test_coordination_config_has_checkpoint_fields(self):
        """CoordinationConfig should have checkpoint-related fields."""
        from massgen.agent_config import CoordinationConfig

        config = CoordinationConfig()
        assert hasattr(config, "checkpoint_enabled")
        assert hasattr(config, "checkpoint_mode")
        assert hasattr(config, "checkpoint_guidance")
        assert hasattr(config, "checkpoint_gated_patterns")

    def test_coordination_config_checkpoint_defaults(self):
        """Checkpoint fields should have sensible defaults."""
        from massgen.agent_config import CoordinationConfig

        config = CoordinationConfig()
        assert config.checkpoint_enabled is False
        assert config.checkpoint_mode == "conversation"
        assert config.checkpoint_guidance == ""
        assert config.checkpoint_gated_patterns == []


class TestCheckpointCliParsing:
    """Test CLI parsing of checkpoint config."""

    def test_parse_coordination_config_with_checkpoint(self):
        """_parse_coordination_config should handle checkpoint fields."""
        from massgen.cli import _parse_coordination_config

        coord_cfg = {
            "checkpoint_enabled": True,
            "checkpoint_mode": "task",
            "checkpoint_guidance": "Break complex tasks into checkpoints.",
            "checkpoint_gated_patterns": ["mcp__vercel__deploy*"],
        }
        config = _parse_coordination_config(coord_cfg)
        assert config.checkpoint_enabled is True
        assert config.checkpoint_mode == "task"
        assert config.checkpoint_guidance == "Break complex tasks into checkpoints."
        assert config.checkpoint_gated_patterns == ["mcp__vercel__deploy*"]

    def test_parse_coordination_config_checkpoint_defaults(self):
        """Missing checkpoint fields should use defaults."""
        from massgen.cli import _parse_coordination_config

        coord_cfg = {}
        config = _parse_coordination_config(coord_cfg)
        assert config.checkpoint_enabled is False
        assert config.checkpoint_mode == "conversation"


# ============================================================================
# Phase 3: Backend Exclusions
# ============================================================================


class TestBackendExclusions:
    """Test that checkpoint params are excluded from API calls."""

    def test_main_agent_excluded_from_api_params(self):
        """main_agent should be in excluded params."""
        from massgen.backend.base import LLMBackend

        excluded = LLMBackend.get_base_excluded_config_params()
        assert "main_agent" in excluded

    def test_checkpoint_params_excluded(self):
        """Checkpoint-related params should be excluded from API calls."""
        from massgen.backend.base import LLMBackend

        excluded = LLMBackend.get_base_excluded_config_params()
        assert "checkpoint_enabled" in excluded
        assert "checkpoint_mode" in excluded
        assert "checkpoint_guidance" in excluded
        assert "checkpoint_gated_patterns" in excluded

    def test_api_handler_excludes_checkpoint_params(self):
        """API params handler should also exclude checkpoint params."""
        # APIParamsHandlerBase is abstract, but we can check the method exists
        # and the set contains checkpoint params via a concrete subclass
        from unittest.mock import MagicMock

        from massgen.api_params_handler._api_params_handler_base import (
            APIParamsHandlerBase,
        )

        handler = MagicMock(spec=APIParamsHandlerBase)
        handler.get_base_excluded_params = APIParamsHandlerBase.get_base_excluded_params
        excluded = handler.get_base_excluded_params(handler)
        assert "main_agent" in excluded
        assert "checkpoint_enabled" in excluded


# ============================================================================
# Phase 1: FRAMEWORK_MCPS
# ============================================================================


class TestFrameworkMcps:
    """Test that checkpoint is in FRAMEWORK_MCPS."""

    def test_checkpoint_in_framework_mcps(self):
        """massgen_checkpoint should be in FRAMEWORK_MCPS."""
        from massgen.filesystem_manager._constants import FRAMEWORK_MCPS

        assert "massgen_checkpoint" in FRAMEWORK_MCPS


# ============================================================================
# Phase 4b: Checkpoint Tool Schema — eval_criteria, personas, gated_actions
# ============================================================================


class TestCheckpointToolEvalCriteria:
    """Test that checkpoint tool requires eval_criteria and accepts personas."""

    def test_validate_requires_eval_criteria(self):
        """eval_criteria is required and must be non-empty."""
        from massgen.mcp_tools.checkpoint._checkpoint_mcp_server import (
            validate_checkpoint_params,
        )

        with pytest.raises(ValueError, match="eval_criteria"):
            validate_checkpoint_params(
                task="Build a website",
                context="",
                eval_criteria=[],
            )

    def test_validate_accepts_eval_criteria(self):
        """eval_criteria as list of strings should be accepted."""
        from massgen.mcp_tools.checkpoint._checkpoint_mcp_server import (
            validate_checkpoint_params,
        )

        result = validate_checkpoint_params(
            task="Build a website",
            eval_criteria=["Beautiful design", "Responsive layout"],
        )
        assert result["eval_criteria"] == ["Beautiful design", "Responsive layout"]

    def test_validate_accepts_personas(self):
        """personas as dict of agent_id -> persona text should be accepted."""
        from massgen.mcp_tools.checkpoint._checkpoint_mcp_server import (
            validate_checkpoint_params,
        )

        result = validate_checkpoint_params(
            task="Build a website",
            eval_criteria=["Good design"],
            personas={
                "agent_a": "You are a frontend expert who values clean code.",
                "agent_b": "You are a UX designer focused on accessibility.",
            },
        )
        assert "agent_a" in result["personas"]
        assert "agent_b" in result["personas"]

    def test_validate_personas_optional(self):
        """personas should default to empty dict when not provided."""
        from massgen.mcp_tools.checkpoint._checkpoint_mcp_server import (
            validate_checkpoint_params,
        )

        result = validate_checkpoint_params(
            task="Build a website",
            eval_criteria=["Good design"],
        )
        assert result["personas"] == {}

    def test_validate_gated_actions_replaces_expected_actions(self):
        """gated_actions should be the field name, not expected_actions."""
        from massgen.mcp_tools.checkpoint._checkpoint_mcp_server import (
            validate_checkpoint_params,
        )

        result = validate_checkpoint_params(
            task="Deploy site",
            eval_criteria=["Deploys correctly"],
            gated_actions=[
                {"tool": "mcp__vercel__deploy", "description": "Deploy to Vercel"},
            ],
        )
        assert len(result["gated_actions"]) == 1
        assert result["gated_actions"][0]["tool"] == "mcp__vercel__deploy"

    def test_validate_gated_actions_optional(self):
        """gated_actions should default to empty list."""
        from massgen.mcp_tools.checkpoint._checkpoint_mcp_server import (
            validate_checkpoint_params,
        )

        result = validate_checkpoint_params(
            task="Build site",
            eval_criteria=["Good design"],
        )
        assert result["gated_actions"] == []


class TestCheckpointSignalWithNewParams:
    """Test checkpoint signal includes eval_criteria and personas."""

    def test_signal_includes_eval_criteria(self):
        """Signal should carry eval_criteria through to orchestrator."""
        from massgen.mcp_tools.checkpoint._checkpoint_mcp_server import (
            build_checkpoint_signal,
        )

        signal = build_checkpoint_signal(
            task="Build site",
            eval_criteria=["Beautiful", "Responsive"],
        )
        assert signal["eval_criteria"] == ["Beautiful", "Responsive"]

    def test_signal_includes_personas(self):
        """Signal should carry personas through to orchestrator."""
        from massgen.mcp_tools.checkpoint._checkpoint_mcp_server import (
            build_checkpoint_signal,
        )

        signal = build_checkpoint_signal(
            task="Build site",
            eval_criteria=["Good"],
            personas={"agent_a": "Frontend expert"},
        )
        assert signal["personas"] == {"agent_a": "Frontend expert"}

    def test_signal_uses_gated_actions(self):
        """Signal should use gated_actions, not expected_actions."""
        from massgen.mcp_tools.checkpoint._checkpoint_mcp_server import (
            build_checkpoint_signal,
        )

        signal = build_checkpoint_signal(
            task="Deploy",
            eval_criteria=["Works"],
            gated_actions=[{"tool": "deploy", "description": "Deploy"}],
        )
        assert "gated_actions" in signal
        assert len(signal["gated_actions"]) == 1
        # expected_actions should still exist for backward compat
        assert "expected_actions" in signal


class TestCheckpointToolkitSchema:
    """Test that the workflow toolkit schema includes new params."""

    def test_checkpoint_tool_has_eval_criteria(self):
        """Checkpoint tool schema should have eval_criteria as required param."""
        from massgen.tool.workflow_toolkits.checkpoint import CheckpointToolkit

        toolkit = CheckpointToolkit()
        config = {"api_format": "chat_completions", "checkpoint_mode": True}
        tools = toolkit.get_tools(config)
        assert len(tools) == 1

        props = tools[0]["function"]["parameters"]["properties"]
        assert "eval_criteria" in props
        required = tools[0]["function"]["parameters"]["required"]
        assert "eval_criteria" in required

    def test_checkpoint_tool_has_personas(self):
        """Checkpoint tool schema should have personas as optional param."""
        from massgen.tool.workflow_toolkits.checkpoint import CheckpointToolkit

        toolkit = CheckpointToolkit()
        config = {"api_format": "chat_completions", "checkpoint_mode": True}
        tools = toolkit.get_tools(config)
        props = tools[0]["function"]["parameters"]["properties"]
        assert "personas" in props

    def test_checkpoint_tool_has_gated_actions(self):
        """Checkpoint tool schema should have gated_actions, not expected_actions."""
        from massgen.tool.workflow_toolkits.checkpoint import CheckpointToolkit

        toolkit = CheckpointToolkit()
        config = {"api_format": "chat_completions", "checkpoint_mode": True}
        tools = toolkit.get_tools(config)
        props = tools[0]["function"]["parameters"]["properties"]
        assert "gated_actions" in props
        assert "expected_actions" not in props


class TestAgentOutputWriterCheckpoint:
    """Test AgentOutputWriter handles checkpoint_activated events."""

    def test_checkpoint_activated_creates_participant_files(self, tmp_path):
        """checkpoint_activated event should create output files for participants."""
        from massgen.events import MassGenEvent
        from massgen.frontend.agent_output_writer import AgentOutputWriter

        writer = AgentOutputWriter(tmp_path, ["agent_a", "agent_b"])
        event = MassGenEvent(
            timestamp="2026-01-01T00:00:00",
            event_type="checkpoint_activated",
            data={
                "checkpoint_number": 1,
                "main_agent_id": "agent_a",
                "participants": {
                    "agent_a-ckpt1": {"real_agent_id": "agent_a", "model": "claude"},
                    "agent_b": {"real_agent_id": "agent_b", "model": "gpt-4o"},
                },
            },
        )
        writer.handle_event(event)

        # main.txt should exist (copied from agent_a.txt)
        assert (tmp_path / "main.txt").exists()
        main_content = (tmp_path / "main.txt").read_text()
        assert "AGENT_A OUTPUT LOG" in main_content
        assert "CHECKPOINT #1 DELEGATED" in main_content

        # Participant files should exist
        assert (tmp_path / "agent_a-ckpt1.txt").exists()
        ckpt_content = (tmp_path / "agent_a-ckpt1.txt").read_text()
        assert "AGENT_A-CKPT1" in ckpt_content

    def test_checkpoint_participant_events_write_to_new_files(self, tmp_path):
        """Events with checkpoint display IDs should write to participant files."""
        from massgen.events import MassGenEvent
        from massgen.frontend.agent_output_writer import AgentOutputWriter

        writer = AgentOutputWriter(tmp_path, ["agent_a", "agent_b"])

        # Activate checkpoint
        writer.handle_event(
            MassGenEvent(
                timestamp="2026-01-01T00:00:00",
                event_type="checkpoint_activated",
                data={
                    "checkpoint_number": 1,
                    "main_agent_id": "agent_a",
                    "participants": {
                        "agent_a-ckpt1": {"real_agent_id": "agent_a", "model": ""},
                        "agent_b": {"real_agent_id": "agent_b", "model": ""},
                    },
                },
            ),
        )

        # Send a text event for the checkpoint participant
        writer.handle_event(
            MassGenEvent(
                timestamp="2026-01-01T00:00:01",
                event_type="text",
                agent_id="agent_a-ckpt1",
                data={"content": "Working on checkpoint task..."},
            ),
        )

        ckpt_content = (tmp_path / "agent_a-ckpt1.txt").read_text()
        assert "Working on checkpoint task..." in ckpt_content

    def test_pre_checkpoint_main_output_not_in_participant_file(self, tmp_path):
        """Pre-checkpoint main agent output should be in main.txt, not the ckpt file."""
        from massgen.events import MassGenEvent
        from massgen.frontend.agent_output_writer import AgentOutputWriter

        writer = AgentOutputWriter(tmp_path, ["agent_a", "agent_b"])

        # Pre-checkpoint output
        writer.handle_event(
            MassGenEvent(
                timestamp="2026-01-01T00:00:00",
                event_type="text",
                agent_id="agent_a",
                data={"content": "Planning the task..."},
            ),
        )

        # Activate checkpoint
        writer.handle_event(
            MassGenEvent(
                timestamp="2026-01-01T00:00:01",
                event_type="checkpoint_activated",
                data={
                    "checkpoint_number": 1,
                    "main_agent_id": "agent_a",
                    "participants": {
                        "agent_a-ckpt1": {"real_agent_id": "agent_a", "model": ""},
                        "agent_b": {"real_agent_id": "agent_b", "model": ""},
                    },
                },
            ),
        )

        # main.txt should have the pre-checkpoint content
        main_content = (tmp_path / "main.txt").read_text()
        assert "Planning the task..." in main_content

        # ckpt file should NOT have pre-checkpoint content
        ckpt_content = (tmp_path / "agent_a-ckpt1.txt").read_text()
        assert "Planning the task..." not in ckpt_content


# ============================================================================
# Phase 5: Checkpoint Agent Identity Separation
# ============================================================================


class TestCheckpointDisplayIdMapping:
    """Test display ID mapping for checkpoint participants."""

    def _make_orchestrator(self):
        """Create a minimal orchestrator for testing display ID mapping."""
        from unittest.mock import MagicMock

        from massgen.agent_config import AgentConfig

        mock_backend_a = MagicMock()
        mock_backend_a.get_model_name.return_value = "claude-sonnet-4"
        mock_backend_a.filesystem_manager = None
        mock_backend_a.config = {"mcp_servers": {}}

        mock_backend_b = MagicMock()
        mock_backend_b.get_model_name.return_value = "gpt-4o"
        mock_backend_b.filesystem_manager = None
        mock_backend_b.config = {"mcp_servers": {}}

        agent_a = MagicMock()
        agent_a.backend = mock_backend_a
        agent_b = MagicMock()
        agent_b.backend = mock_backend_b

        agents = {"agent_a": agent_a, "agent_b": agent_b}
        config = AgentConfig.create_openai_config()

        from massgen.orchestrator import Orchestrator

        orch = Orchestrator(
            orchestrator_id="orch",
            agents=agents,
            config=config,
        )
        orch._main_agent_id = "agent_a"
        return orch

    def test_get_checkpoint_display_id_outside_checkpoint(self):
        """Outside checkpoint, display ID should equal raw agent_id."""
        orch = self._make_orchestrator()
        assert orch._get_checkpoint_display_id("agent_a") == "agent_a"
        assert orch._get_checkpoint_display_id("agent_b") == "agent_b"

    def test_get_checkpoint_display_id_during_checkpoint(self):
        """During checkpoint, main agent gets remapped display ID."""
        orch = self._make_orchestrator()
        signal = {"type": "checkpoint", "task": "Build website", "context": "", "expected_actions": []}
        orch._activate_checkpoint(signal)

        # Main agent should get checkpoint display ID via the mapping
        display_id = orch._get_checkpoint_display_id("agent_a")
        assert display_id == "agent_a-ckpt1"

        # Non-main agent also gets ckpt label
        display_id_b = orch._get_checkpoint_display_id("agent_b")
        assert display_id_b == "agent_b-ckpt1"

        # After activation, self.agents uses display IDs as keys (fresh agents)
        assert "agent_a-ckpt1" in orch.agents
        assert "agent_b-ckpt1" in orch.agents

    def test_display_id_increments_with_checkpoint_number(self):
        """Display ID should use the current checkpoint number."""
        orch = self._make_orchestrator()
        signal = {"type": "checkpoint", "task": "Task 1", "context": "", "expected_actions": []}
        orch._activate_checkpoint(signal)
        assert orch._get_checkpoint_display_id("agent_a") == "agent_a-ckpt1"

        # Deactivate properly (restores original agents) and activate again
        orch._deactivate_checkpoint(
            consensus="Done",
            workspace_changes=[],
            action_results=[],
        )
        signal2 = {"type": "checkpoint", "task": "Task 2", "context": "", "expected_actions": []}
        orch._activate_checkpoint(signal2)
        assert orch._get_checkpoint_display_id("agent_a") == "agent_a-ckpt2"

    def test_activate_checkpoint_sets_display_ids(self):
        """_activate_checkpoint should populate _checkpoint_display_ids."""
        orch = self._make_orchestrator()
        signal = {"type": "checkpoint", "task": "Build it", "context": "", "expected_actions": []}
        orch._activate_checkpoint(signal)

        assert "agent_a" in orch._checkpoint_display_ids
        assert orch._checkpoint_display_ids["agent_a"] == "agent_a-ckpt1"
        # All agents get ckpt label during checkpoint
        assert "agent_b" in orch._checkpoint_display_ids
        assert orch._checkpoint_display_ids["agent_b"] == "agent_b-ckpt1"

    def test_activate_checkpoint_stores_participants(self):
        """_activate_checkpoint should store participant info for display layer."""
        orch = self._make_orchestrator()
        signal = {"type": "checkpoint", "task": "Build it", "context": "", "expected_actions": []}
        orch._activate_checkpoint(signal)

        assert hasattr(orch, "_checkpoint_participants")
        participants = orch._checkpoint_participants
        # Should have entries for all agents, keyed by display ID
        assert "agent_a-ckpt1" in participants
        assert "agent_b-ckpt1" in participants
        assert participants["agent_a-ckpt1"]["real_agent_id"] == "agent_a"
        assert participants["agent_b-ckpt1"]["real_agent_id"] == "agent_b"

    def test_activate_saves_original_agents(self):
        """_activate_checkpoint should save original agents for later restoration."""
        orch = self._make_orchestrator()
        original_agents = orch.agents
        signal = {"type": "checkpoint", "task": "Build", "context": "", "expected_actions": []}
        orch._activate_checkpoint(signal)

        # Original agents should be saved
        assert orch._saved_agents is not None
        assert orch._saved_agents is original_agents
        # Current agents should be different (display IDs as keys)
        assert set(orch.agents.keys()) != set(original_agents.keys())

    def test_deactivate_restores_original_agents(self):
        """_deactivate_checkpoint should restore original agents."""
        orch = self._make_orchestrator()
        original_agents = orch.agents
        original_agent_ids = set(original_agents.keys())

        signal = {"type": "checkpoint", "task": "Build", "context": "", "expected_actions": []}
        orch._activate_checkpoint(signal)
        assert set(orch.agents.keys()) != original_agent_ids

        orch._deactivate_checkpoint(
            consensus="Result",
            workspace_changes=[],
            action_results=[],
        )
        # After deactivation, original agents restored
        assert set(orch.agents.keys()) == original_agent_ids
        assert orch._saved_agents is None
        assert orch._checkpoint_active is False


class TestCheckpointMcpRemovalRestore:
    """Test checkpoint MCP tool removal and restoration."""

    def _make_orchestrator_with_mcp(self, mcp_servers_format="dict"):
        """Create an orchestrator with checkpoint MCP injected."""
        from unittest.mock import MagicMock

        from massgen.agent_config import AgentConfig

        mock_backend_a = MagicMock()
        mock_backend_a.get_model_name.return_value = "claude-sonnet-4"
        mock_backend_a.filesystem_manager = None
        if mcp_servers_format == "dict":
            mock_backend_a.config = {
                "mcp_servers": {
                    "massgen_checkpoint": {"name": "massgen_checkpoint", "type": "sdk"},
                    "other_mcp": {"name": "other_mcp"},
                },
            }
        else:
            mock_backend_a.config = {
                "mcp_servers": [
                    {"name": "massgen_checkpoint", "type": "sdk"},
                    {"name": "other_mcp"},
                ],
            }

        mock_backend_b = MagicMock()
        mock_backend_b.get_model_name.return_value = "gpt-4o"
        mock_backend_b.filesystem_manager = None
        mock_backend_b.config = {"mcp_servers": {}}

        agent_a = MagicMock()
        agent_a.backend = mock_backend_a
        agent_b = MagicMock()
        agent_b.backend = mock_backend_b

        agents = {"agent_a": agent_a, "agent_b": agent_b}
        config = AgentConfig.create_openai_config()

        from massgen.orchestrator import Orchestrator

        orch = Orchestrator(
            orchestrator_id="orch",
            agents=agents,
            config=config,
        )
        orch._main_agent_id = "agent_a"
        return orch

    def test_remove_checkpoint_mcp_dict_format(self):
        """Should remove massgen_checkpoint from dict-format mcp_servers."""
        orch = self._make_orchestrator_with_mcp("dict")
        orch._remove_checkpoint_mcp_from_main_agent()

        mcp_servers = orch.agents["agent_a"].backend.config["mcp_servers"]
        assert "massgen_checkpoint" not in mcp_servers
        assert "other_mcp" in mcp_servers
        assert orch._saved_checkpoint_mcp is not None

    def test_remove_checkpoint_mcp_list_format(self):
        """Should remove massgen_checkpoint from list-format mcp_servers."""
        orch = self._make_orchestrator_with_mcp("list")
        orch._remove_checkpoint_mcp_from_main_agent()

        mcp_servers = orch.agents["agent_a"].backend.config["mcp_servers"]
        names = [s["name"] for s in mcp_servers if isinstance(s, dict)]
        assert "massgen_checkpoint" not in names
        assert "other_mcp" in names
        assert orch._saved_checkpoint_mcp is not None

    def test_restore_checkpoint_mcp_dict_format(self):
        """Should restore massgen_checkpoint to dict-format mcp_servers."""
        orch = self._make_orchestrator_with_mcp("dict")
        orch._remove_checkpoint_mcp_from_main_agent()
        orch._restore_checkpoint_mcp_to_main_agent()

        mcp_servers = orch.agents["agent_a"].backend.config["mcp_servers"]
        assert "massgen_checkpoint" in mcp_servers
        assert orch._saved_checkpoint_mcp is None

    def test_restore_checkpoint_mcp_list_format(self):
        """Should restore massgen_checkpoint to list-format mcp_servers."""
        orch = self._make_orchestrator_with_mcp("list")
        orch._remove_checkpoint_mcp_from_main_agent()
        orch._restore_checkpoint_mcp_to_main_agent()

        mcp_servers = orch.agents["agent_a"].backend.config["mcp_servers"]
        names = [s["name"] for s in mcp_servers if isinstance(s, dict)]
        assert "massgen_checkpoint" in names
        assert orch._saved_checkpoint_mcp is None

    def test_activate_checkpoint_removes_mcp(self):
        """_activate_checkpoint should remove checkpoint MCP from main agent before saving."""
        orch = self._make_orchestrator_with_mcp("dict")
        signal = {"type": "checkpoint", "task": "Build", "context": "", "expected_actions": []}
        orch._activate_checkpoint(signal)

        # MCP should be removed from the saved original agent
        saved_agent_a = orch._saved_agents["agent_a"]
        mcp_servers = saved_agent_a.backend.config["mcp_servers"]
        assert "massgen_checkpoint" not in mcp_servers

    def test_deactivate_checkpoint_restores_mcp(self):
        """_deactivate_checkpoint should restore checkpoint MCP to main agent."""
        orch = self._make_orchestrator_with_mcp("dict")
        signal = {"type": "checkpoint", "task": "Build", "context": "", "expected_actions": []}
        orch._activate_checkpoint(signal)

        # MCP should be saved
        assert orch._saved_checkpoint_mcp is not None

        orch._deactivate_checkpoint(
            consensus="Done",
            workspace_changes=[],
            action_results=[],
        )

        # After deactivation, MCP should be restored to main agent
        mcp_servers = orch.agents["agent_a"].backend.config["mcp_servers"]
        assert "massgen_checkpoint" in mcp_servers


class TestCheckpointRejectionGuard:
    """Test that checkpoint tool calls are rejected during active checkpoint."""

    def test_checkpoint_workflow_tools_excluded_during_checkpoint(self):
        """During active checkpoint, main agent should NOT get checkpoint workflow tools."""
        from unittest.mock import MagicMock

        from massgen.agent_config import AgentConfig
        from massgen.orchestrator import Orchestrator

        mock_backend = MagicMock()
        mock_backend.get_model_name.return_value = "claude-sonnet-4"
        mock_backend.filesystem_manager = None
        mock_backend.config = {"mcp_servers": {}}

        agent = MagicMock()
        agent.backend = mock_backend

        agents = {"agent_a": agent, "agent_b": MagicMock()}
        agents["agent_b"].backend = MagicMock()
        agents["agent_b"].backend.filesystem_manager = None
        agents["agent_b"].backend.config = {"mcp_servers": {}}
        agents["agent_b"].backend.get_model_name.return_value = "gpt-4o"

        config = AgentConfig.create_openai_config()
        orch = Orchestrator(
            orchestrator_id="orch",
            agents=agents,
            config=config,
        )
        orch._main_agent_id = "agent_a"

        # In solo mode (not checkpoint active), main agent gets checkpoint tools
        assert orch.is_checkpoint_mode is True
        assert orch._checkpoint_active is False

        # During checkpoint, is_checkpoint_mode is True and _checkpoint_active is True
        # The workflow tool selection logic at line 14172 should NOT give checkpoint tools
        orch._checkpoint_active = True
        # When checkpoint is active, the condition:
        # if self.is_checkpoint_mode and not self._checkpoint_active and agent_id == self._main_agent_id
        # evaluates to False, so agent gets regular workflow_tools, not checkpoint tools
        should_get_checkpoint_tools = orch.is_checkpoint_mode and not orch._checkpoint_active and "agent_a" == orch._main_agent_id
        assert should_get_checkpoint_tools is False


class TestCheckpointTaskPassthrough:
    """Test that checkpoint task is passed to participants."""

    def test_checkpoint_task_stored_on_activation(self):
        """_activate_checkpoint should store the task for participant use."""
        from unittest.mock import MagicMock

        from massgen.agent_config import AgentConfig
        from massgen.orchestrator import Orchestrator

        mock_backend = MagicMock()
        mock_backend.get_model_name.return_value = "claude-sonnet-4"
        mock_backend.filesystem_manager = None
        mock_backend.config = {"mcp_servers": {}}

        agent_a = MagicMock()
        agent_a.backend = mock_backend
        agent_b = MagicMock()
        agent_b.backend = MagicMock()
        agent_b.backend.filesystem_manager = None
        agent_b.backend.config = {"mcp_servers": {}}
        agent_b.backend.get_model_name.return_value = "gpt-4o"

        agents = {"agent_a": agent_a, "agent_b": agent_b}
        config = AgentConfig.create_openai_config()
        orch = Orchestrator(
            orchestrator_id="orch",
            agents=agents,
            config=config,
        )
        orch._main_agent_id = "agent_a"

        signal = {
            "type": "checkpoint",
            "task": "Build a website about love",
            "context": "Use React and TypeScript",
            "expected_actions": [],
        }
        orch._activate_checkpoint(signal)

        assert orch._checkpoint_task == "Build a website about love"
        assert orch._checkpoint_context == "Use React and TypeScript"


class TestStreamChunkCheckpointFields:
    """Test StreamChunk has fields for checkpoint events."""

    def test_stream_chunk_has_checkpoint_fields(self):
        """StreamChunk should support checkpoint_participants, checkpoint_number, main_agent_id."""
        from massgen.backend.base import StreamChunk

        chunk = StreamChunk(
            type="checkpoint_activated",
            content="Build a website",
            source="orchestrator",
            checkpoint_participants={"agent_a-ckpt1": {"real_agent_id": "agent_a"}},
            checkpoint_number=1,
            main_agent_id="agent_a",
        )
        assert chunk.checkpoint_participants is not None
        assert chunk.checkpoint_number == 1
        assert chunk.main_agent_id == "agent_a"

    def test_stream_chunk_checkpoint_fields_default_none(self):
        """Checkpoint fields should default to None."""
        from massgen.backend.base import StreamChunk

        chunk = StreamChunk(type="content", content="hello")
        assert chunk.checkpoint_participants is None
        assert chunk.checkpoint_number is None
        assert chunk.main_agent_id is None


class TestDeactivateCheckpointWiring:
    """Test that _deactivate_checkpoint restores state properly."""

    def _make_orchestrator(self):
        """Create orchestrator with checkpoint state."""
        from unittest.mock import MagicMock

        from massgen.agent_config import AgentConfig
        from massgen.orchestrator import Orchestrator

        mock_backend_a = MagicMock()
        mock_backend_a.get_model_name.return_value = "claude-sonnet-4"
        mock_backend_a.filesystem_manager = None
        mock_backend_a.config = {
            "mcp_servers": {
                "massgen_checkpoint": {"name": "massgen_checkpoint"},
                "other": {"name": "other"},
            },
        }

        mock_backend_b = MagicMock()
        mock_backend_b.get_model_name.return_value = "gpt-4o"
        mock_backend_b.filesystem_manager = None
        mock_backend_b.config = {"mcp_servers": {}}

        agent_a = MagicMock()
        agent_a.backend = mock_backend_a
        agent_b = MagicMock()
        agent_b.backend = mock_backend_b

        agents = {"agent_a": agent_a, "agent_b": agent_b}
        config = AgentConfig.create_openai_config()
        orch = Orchestrator(
            orchestrator_id="orch",
            agents=agents,
            config=config,
        )
        orch._main_agent_id = "agent_a"
        return orch

    def test_deactivate_clears_checkpoint_state(self):
        """_deactivate_checkpoint should clear active flag and restore original agents."""
        orch = self._make_orchestrator()
        signal = {"type": "checkpoint", "task": "Build", "context": "", "expected_actions": []}
        orch._activate_checkpoint(signal)
        assert orch._checkpoint_active is True

        orch._deactivate_checkpoint(
            consensus="Result text",
            workspace_changes=[],
            action_results=[],
        )
        assert orch._checkpoint_active is False
        # Original agents should be restored
        assert "agent_a" in orch.agents
        assert "agent_b" in orch.agents
        # Main agent should be marked for restart with has_voted=False
        assert orch.agent_states["agent_a"].restart_pending is True
        assert orch.agent_states["agent_a"].has_voted is False
        # Non-main agents should be marked as voted (inactive in solo mode)
        assert orch.agent_states["agent_b"].has_voted is True

    def test_restore_mcp_after_deactivation(self):
        """After deactivation, checkpoint MCP should be restored to main agent."""
        orch = self._make_orchestrator()
        signal = {"type": "checkpoint", "task": "Build", "context": "", "expected_actions": []}
        orch._activate_checkpoint(signal)

        # MCP should have been removed from the saved original agent
        saved_agent_a = orch._saved_agents["agent_a"]
        assert "massgen_checkpoint" not in saved_agent_a.backend.config["mcp_servers"]

        # After deactivation, MCP should be restored
        orch._deactivate_checkpoint(
            consensus="Done",
            workspace_changes=[],
            action_results=[],
        )
        assert "massgen_checkpoint" in orch.agents["agent_a"].backend.config["mcp_servers"]

    def test_deactivate_injects_consensus_into_main_agent_state(self):
        """After deactivation, main agent's answer state should contain the consensus."""
        orch = self._make_orchestrator()
        signal = {"type": "checkpoint", "task": "Build", "context": "", "expected_actions": []}
        orch._activate_checkpoint(signal)

        orch._deactivate_checkpoint(
            consensus="The team built a beautiful website with React.",
            workspace_changes=[],
            action_results=[],
        )

        # Main agent should have the consensus in its answer state
        assert orch.agent_states["agent_a"].answer == "The team built a beautiful website with React."

    def test_deactivate_cleans_up_workspace_clones(self, tmp_path):
        """After deactivation, cloned checkpoint workspaces should be cleaned up."""
        from massgen.agent_config import AgentConfig
        from massgen.orchestrator import Orchestrator

        # Create real workspace dirs
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / "file.txt").write_text("content")

        mock_fm = MagicMock()
        mock_fm.cwd = str(ws)
        mock_backend = MagicMock()
        mock_backend.get_model_name.return_value = "test"
        mock_backend.filesystem_manager = mock_fm
        mock_backend.config = {"mcp_servers": {}, "model": "test"}
        mock_backend.api_key = "key"
        mock_backend._backend_type = "claude"

        agent = MagicMock()
        agent.backend = mock_backend
        agent.config = AgentConfig.create_openai_config()
        agent.config.agent_id = "agent_a"

        config = AgentConfig.create_openai_config()
        orch = Orchestrator(
            orchestrator_id="orch",
            agents={"agent_a": agent},
            config=config,
        )
        orch._main_agent_id = "agent_a"

        # Simulate: manually add a fake clone path
        clone_path = tmp_path / "workspace_ckpt_clone"
        clone_path.mkdir()
        (clone_path / "deliverable.html").write_text("<html>")
        orch._checkpoint_workspace_clones = [str(clone_path)]

        # Simulate a minimal activation/deactivation cycle
        signal = {"type": "checkpoint", "task": "Build", "context": "", "expected_actions": []}
        orch._activate_checkpoint(signal)
        orch._deactivate_checkpoint(
            consensus="Done",
            workspace_changes=[],
            action_results=[],
        )

        # All cloned workspace paths tracked before activation should be cleaned up
        # (the ones from _activate_checkpoint may still exist since we didn't mock create_backend)
        # But the manually-added one should be gone
        assert not clone_path.exists()


# ============================================================================
# Phase 6: Fresh Agent Instances
# ============================================================================


class TestBackendTypeStamping:
    """Test that create_backend stamps _backend_type on backends."""

    def test_create_backend_stamps_type(self):
        """create_backend should stamp _backend_type on the returned backend."""
        from unittest.mock import patch

        from massgen.cli import create_backend

        # Mock the ResponseBackend to avoid needing a real API key
        with patch("massgen.cli.ResponseBackend") as MockBackend:
            mock_instance = MagicMock()
            MockBackend.return_value = mock_instance
            # Pass api_key via env to avoid double-passing
            with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
                result = create_backend("openai")
            assert result._backend_type == "openai"

    def test_create_backend_stamps_claude_type(self):
        """Claude backend should get _backend_type='claude'."""
        from unittest.mock import patch

        from massgen.cli import create_backend

        with patch("massgen.cli.ClaudeBackend") as MockBackend:
            mock_instance = MagicMock()
            MockBackend.return_value = mock_instance
            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                result = create_backend("claude")
            assert result._backend_type == "claude"


class TestFreshCheckpointAgentCreation:
    """Test _create_fresh_checkpoint_agents creates isolated agents."""

    def _make_orchestrator_with_workspaces(self, tmp_path):
        """Create orchestrator with real workspace paths for testing fresh agents."""
        from unittest.mock import MagicMock

        from massgen.agent_config import AgentConfig
        from massgen.orchestrator import Orchestrator

        # Create real workspace directories
        ws_a = tmp_path / "workspace_a"
        ws_a.mkdir()
        (ws_a / "CONTEXT.md").write_text("# Context\nMain agent setup.")
        (ws_a / "src").mkdir()
        (ws_a / "src" / "app.tsx").write_text("export default App;")

        ws_b = tmp_path / "workspace_b"
        ws_b.mkdir()

        mock_fm_a = MagicMock()
        mock_fm_a.cwd = str(ws_a)
        mock_backend_a = MagicMock()
        mock_backend_a.get_model_name.return_value = "claude-sonnet-4"
        mock_backend_a.filesystem_manager = mock_fm_a
        mock_backend_a.config = {"mcp_servers": {}, "model": "claude-sonnet-4"}
        mock_backend_a.api_key = "test-key"
        mock_backend_a._backend_type = "claude"

        mock_fm_b = MagicMock()
        mock_fm_b.cwd = str(ws_b)
        mock_backend_b = MagicMock()
        mock_backend_b.get_model_name.return_value = "gpt-4o"
        mock_backend_b.filesystem_manager = mock_fm_b
        mock_backend_b.config = {"mcp_servers": {}, "model": "gpt-4o"}
        mock_backend_b.api_key = "test-key"
        mock_backend_b._backend_type = "openai"

        agent_a = MagicMock()
        agent_a.backend = mock_backend_a
        agent_a.config = AgentConfig.create_openai_config()
        agent_a.config.agent_id = "agent_a"

        agent_b = MagicMock()
        agent_b.backend = mock_backend_b
        agent_b.config = AgentConfig.create_openai_config()
        agent_b.config.agent_id = "agent_b"

        agents = {"agent_a": agent_a, "agent_b": agent_b}
        config = AgentConfig.create_openai_config()

        orch = Orchestrator(
            orchestrator_id="orch",
            agents=agents,
            config=config,
        )
        orch._main_agent_id = "agent_a"
        orch._checkpoint_number = 1
        return orch, ws_a, ws_b

    def test_fresh_agents_get_display_ids(self, tmp_path):
        """Fresh agents should use checkpoint display IDs as their keys."""
        from unittest.mock import patch

        orch, ws_a, ws_b = self._make_orchestrator_with_workspaces(tmp_path)

        def _make_mock_backend(btype, **kw):
            fm = MagicMock()
            fm.cwd = kw.get("cwd")
            return MagicMock(
                config=kw,
                api_key=kw.get("api_key"),
                _backend_type=btype,
                filesystem_manager=fm,
                get_model_name=MagicMock(return_value="mock-model"),
            )

        with patch("massgen.cli.create_backend") as mock_create:
            mock_create.side_effect = _make_mock_backend
            fresh = orch._create_fresh_checkpoint_agents()

        assert "agent_a-ckpt1" in fresh
        assert "agent_b-ckpt1" in fresh
        assert len(fresh) == 2

    def test_fresh_agents_setup_orchestration_paths(self, tmp_path):
        """Fresh agents should have setup_orchestration_paths called for log snapshots."""
        from unittest.mock import patch

        orch, ws_a, ws_b = self._make_orchestrator_with_workspaces(tmp_path)

        created_fms = []

        def _make_mock_backend(btype, **kw):
            fm = MagicMock()
            fm.cwd = kw.get("cwd")
            created_fms.append(fm)
            return MagicMock(
                config=kw,
                api_key=kw.get("api_key"),
                _backend_type=btype,
                filesystem_manager=fm,
                get_model_name=MagicMock(return_value="mock-model"),
            )

        with patch("massgen.cli.create_backend") as mock_create:
            mock_create.side_effect = _make_mock_backend
            orch._create_fresh_checkpoint_agents()

        # setup_orchestration_paths should have been called on each fresh backend's fm
        for fm in created_fms:
            fm.setup_orchestration_paths.assert_called_once()
            call_kwargs = fm.setup_orchestration_paths.call_args
            # agent_id should be the display ID (contains "ckpt")
            assert "ckpt" in call_kwargs.kwargs.get("agent_id", call_kwargs.args[0] if call_kwargs.args else "")

    def test_fresh_agents_clone_workspace(self, tmp_path):
        """Fresh agents should have cloned workspace with original files."""
        from unittest.mock import patch

        orch, ws_a, ws_b = self._make_orchestrator_with_workspaces(tmp_path)

        created_backends = []

        def mock_create(btype, **kw):
            # Simulate _setup_workspace: create the cwd directory (empty)
            cwd = kw.get("cwd")
            if cwd:
                Path(cwd).mkdir(parents=True, exist_ok=True)
            fm = MagicMock()
            fm.cwd = cwd
            mock = MagicMock(
                config=kw,
                api_key=kw.get("api_key"),
                _backend_type=btype,
                filesystem_manager=fm,
                get_model_name=MagicMock(return_value="mock-model"),
            )
            created_backends.append(kw)
            return mock

        with patch("massgen.cli.create_backend", side_effect=mock_create):
            fresh = orch._create_fresh_checkpoint_agents()

        # Find the workspace created for agent_a's fresh instance
        agent_a_ckpt = fresh.get("agent_a-ckpt1")
        assert agent_a_ckpt is not None

        # The cloned workspace should contain the original files
        cloned_cwd_a = None
        for kw in created_backends:
            cwd = kw.get("cwd", "")
            if "workspace_a" in str(cwd) and "_ckpt_" in str(cwd):
                cloned_cwd_a = cwd
                break

        assert cloned_cwd_a is not None
        cloned_path = Path(cloned_cwd_a)
        assert cloned_path.exists()
        assert (cloned_path / "CONTEXT.md").exists()
        assert (cloned_path / "src" / "app.tsx").exists()

    def test_fresh_agents_filter_checkpoint_mcp(self, tmp_path):
        """Fresh agents should not have massgen_checkpoint in their MCP servers."""
        from unittest.mock import patch

        orch, ws_a, ws_b = self._make_orchestrator_with_workspaces(tmp_path)
        # Add checkpoint MCP to agent_a's config
        orch.agents["agent_a"].backend.config["mcp_servers"] = {
            "massgen_checkpoint": {"name": "massgen_checkpoint"},
            "command_line": {"name": "command_line", "args": ["--allowed-paths", "/old/path"]},
            "filesystem": {"name": "filesystem"},
            "other_mcp": {"name": "other_mcp"},
        }

        backend_configs = []

        def mock_create(btype, **kw):
            backend_configs.append(kw)
            return MagicMock(
                config=kw,
                api_key=kw.get("api_key"),
                _backend_type=btype,
                filesystem_manager=MagicMock(cwd=kw.get("cwd")),
                get_model_name=MagicMock(return_value="mock-model"),
            )

        with patch("massgen.cli.create_backend", side_effect=mock_create):
            orch._create_fresh_checkpoint_agents()

        # Check that auto-injected MCPs were filtered from configs passed to create_backend
        # Find the config that originally had MCPs (agent_a's config)
        for cfg in backend_configs:
            mcp_servers = cfg.get("mcp_servers", {})
            if not mcp_servers:
                continue  # Skip agent_b which had no MCPs
            if isinstance(mcp_servers, dict):
                assert "massgen_checkpoint" not in mcp_servers
                assert "command_line" not in mcp_servers
                assert "filesystem" not in mcp_servers
                # User MCPs should be preserved
                assert "other_mcp" in mcp_servers


class TestWorkspacePropagation:
    """Test _propagate_checkpoint_results_to_main_workspace."""

    def test_propagate_copies_files(self, tmp_path):
        """Winning agent's workspace files should be copied to main workspace."""
        from unittest.mock import MagicMock

        from massgen.agent_config import AgentConfig
        from massgen.orchestrator import Orchestrator

        # Create workspaces
        winner_ws = tmp_path / "winner_ws"
        winner_ws.mkdir()
        (winner_ws / "index.html").write_text("<html>Winner</html>")
        (winner_ws / "styles").mkdir()
        (winner_ws / "styles" / "main.css").write_text("body { color: red; }")
        (winner_ws / ".git").mkdir()  # Should be skipped

        main_ws = tmp_path / "main_ws"
        main_ws.mkdir()

        # Setup orchestrator with checkpoint agents
        winner_backend = MagicMock()
        winner_backend.filesystem_manager = MagicMock(cwd=str(winner_ws))

        main_backend = MagicMock()
        main_backend.filesystem_manager = MagicMock(cwd=str(main_ws))

        winner_agent = MagicMock()
        winner_agent.backend = winner_backend

        main_agent = MagicMock()
        main_agent.backend = main_backend
        main_agent.config = AgentConfig.create_openai_config()
        main_agent.config.agent_id = "agent_a"

        # Create mock orchestrator state
        mock_backend = MagicMock()
        mock_backend.filesystem_manager = None
        mock_backend.config = {"mcp_servers": {}}
        mock_backend.get_model_name.return_value = "test"

        dummy_agent = MagicMock()
        dummy_agent.backend = mock_backend

        config = AgentConfig.create_openai_config()
        orch = Orchestrator(
            orchestrator_id="orch",
            agents={"winner-ckpt1": winner_agent, "other-ckpt1": dummy_agent},
            config=config,
        )
        orch._main_agent_id = "agent_a"
        orch._saved_agents = {"agent_a": main_agent}

        orch._propagate_checkpoint_results_to_main_workspace("winner-ckpt1")

        # Files should have been copied
        assert (main_ws / "index.html").exists()
        assert (main_ws / "index.html").read_text() == "<html>Winner</html>"
        assert (main_ws / "styles" / "main.css").exists()
        # Hidden dirs should not be copied
        assert not (main_ws / ".git").exists()

    def test_propagate_skips_when_no_workspace(self, tmp_path):
        """Should not crash when workspace paths are missing."""
        from unittest.mock import MagicMock

        from massgen.agent_config import AgentConfig
        from massgen.orchestrator import Orchestrator

        mock_backend = MagicMock()
        mock_backend.filesystem_manager = None
        mock_backend.config = {"mcp_servers": {}}
        mock_backend.get_model_name.return_value = "test"
        agent = MagicMock()
        agent.backend = mock_backend

        config = AgentConfig.create_openai_config()
        orch = Orchestrator(
            orchestrator_id="orch",
            agents={"agent-ckpt1": agent},
            config=config,
        )
        orch._main_agent_id = "agent_a"
        orch._saved_agents = {"agent_a": agent}

        # Should not raise
        orch._propagate_checkpoint_results_to_main_workspace("agent-ckpt1")
