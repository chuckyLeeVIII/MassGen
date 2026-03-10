"""Tests for task planning mode (--plan flag)."""

from massgen.cli import get_task_planning_prompt_prefix


class TestTaskPlanningPromptPrefix:
    """Test the task planning prompt prefix generation."""

    def test_shallow_depth_prefix(self):
        """Test shallow depth generates appropriate prefix."""
        prefix = get_task_planning_prompt_prefix("shallow")

        # Check key elements are present
        assert "TASK PLANNING MODE" in prefix
        assert "interactively" in prefix
        assert "ask_others" in prefix
        assert "project_plan.json" in prefix  # Project plan stored in deliverable/ or workspace root

        # Check depth-specific content
        assert "SHALLOW" in prefix
        assert "5-10" in prefix
        assert "high-level phases only" in prefix

    def test_medium_depth_prefix(self):
        """Test medium depth generates appropriate prefix."""
        prefix = get_task_planning_prompt_prefix("medium")

        assert "TASK PLANNING MODE" in prefix
        assert "MEDIUM" in prefix
        assert "20-50" in prefix
        assert "sections with tasks" in prefix

    def test_deep_depth_prefix(self):
        """Test deep depth generates appropriate prefix."""
        prefix = get_task_planning_prompt_prefix("deep")

        assert "TASK PLANNING MODE" in prefix
        assert "DEEP" in prefix
        assert "100-200+" in prefix
        assert "granular step-by-step" in prefix

    def test_default_depth_is_medium(self):
        """Test that default depth is medium."""
        prefix = get_task_planning_prompt_prefix()

        assert "MEDIUM" in prefix
        assert "20-50" in prefix

    def test_invalid_depth_defaults_to_medium(self):
        """Test that invalid depth falls back to medium."""
        prefix = get_task_planning_prompt_prefix("invalid")

        # Should fall back to medium config
        assert "20-50" in prefix
        assert "sections with tasks" in prefix

    def test_prefix_contains_feature_list_schema(self):
        """Test that prefix includes the task list JSON schema."""
        prefix = get_task_planning_prompt_prefix("medium")

        # Check JSON schema elements (MCP format)
        assert '"tasks"' in prefix
        assert '"id"' in prefix
        assert '"description"' in prefix  # Combined name + description
        assert '"status"' in prefix
        assert '"depends_on"' in prefix  # Updated from "dependencies"
        assert '"priority"' in prefix

    def test_prefix_contains_interactive_instructions(self):
        """Test that prefix emphasizes interactive questioning."""
        prefix = get_task_planning_prompt_prefix("medium")

        # Check interactive elements
        assert "ask_others" in prefix
        assert "Scope Confirmation" in prefix
        assert "Clarifying Questions" in prefix

    def test_prefix_ends_with_user_request_marker(self):
        """Test that prefix ends with marker for user's request."""
        prefix = get_task_planning_prompt_prefix("medium")

        assert prefix.strip().endswith("USER'S REQUEST:")

    def test_prefix_contains_scope_confirmation_section(self):
        """Test that prefix includes scope confirmation instructions."""
        prefix = get_task_planning_prompt_prefix("medium")

        # Check scope confirmation elements (default is human mode)
        assert "Scope Confirmation" in prefix
        assert "multiple distinct features" in prefix
        assert "assumption" in prefix.lower()
        assert "confirm" in prefix.lower() or "verify" in prefix.lower()

    def test_prefix_without_subagents(self):
        """Test that prefix without subagents doesn't mention them."""
        prefix = get_task_planning_prompt_prefix("medium", enable_subagents=False)

        assert "subagent" not in prefix.lower()
        assert "Research with Subagents" not in prefix

    def test_prefix_with_subagents_enabled(self):
        """Test that prefix with subagents includes research section."""
        prefix = get_task_planning_prompt_prefix("medium", enable_subagents=True)

        # Check subagent research section is present
        assert "Research with Subagents" in prefix
        assert "subagents available for research" in prefix
        assert "Spawn subagents" in prefix

    def test_prefix_mentions_multiple_specs(self):
        """Test that prefix mentions creating separate specs for multiple features."""
        prefix = get_task_planning_prompt_prefix("medium")

        assert "separate spec files" in prefix.lower() or "multiple distinct features" in prefix

    def test_prompt_with_human_broadcast_mode(self):
        """Test that human broadcast mode includes ask_others() guidance."""
        prefix = get_task_planning_prompt_prefix("medium", enable_subagents=False, broadcast_mode="human")

        # Should include ask_others() instructions
        assert "ask_others" in prefix
        assert "Scope Confirmation" in prefix
        assert "Verify ONLY THE MOST CRITICAL assumptions with human" in prefix
        assert "When to ask the human" in prefix
        assert "When NOT to ask the human" in prefix
        assert "GOOD (selective + recommendations)" in prefix

    def test_prompt_without_human_broadcast_mode(self):
        """Test that non-human broadcast mode excludes ask_others() and emphasizes consensus."""
        prefix = get_task_planning_prompt_prefix("medium", enable_subagents=False, broadcast_mode=False)

        # Should NOT include human verification instructions
        assert "ask_others" not in prefix or "don't have human interaction" in prefix
        assert "Scope Analysis" in prefix  # Different title
        assert "Scope Confirmation" not in prefix  # NOT the human version

        # Should emphasize autonomous decision-making
        assert "Make opinionated recommendations for ALL assumptions" in prefix
        assert "you MUST make decisions autonomously" in prefix
        assert "Since you don't have human interaction" in prefix
        assert "ALL decisions must be made through consensus" in prefix

    def test_prompt_with_agents_broadcast_mode(self):
        """Test that agents broadcast mode also excludes human interaction."""
        prefix = get_task_planning_prompt_prefix("medium", enable_subagents=False, broadcast_mode="agents")

        # Should also use autonomous mode (no human)
        assert "Scope Analysis" in prefix
        assert "Make opinionated recommendations for ALL assumptions" in prefix
        assert "consensus" in prefix

    def test_prompt_assumption_categorization(self):
        """Test that prompt includes assumption categorization guidance."""
        prefix_human = get_task_planning_prompt_prefix("medium", broadcast_mode="human")
        prefix_autonomous = get_task_planning_prompt_prefix("medium", broadcast_mode=False)

        # Both modes should have categorization
        for prefix in [prefix_human, prefix_autonomous]:
            assert "Explicitly Stated" in prefix
            assert "Critical Assumptions" in prefix
            assert "Technical/Implementation Assumptions" in prefix

        # Human mode specific
        assert "NEED HUMAN VERIFICATION" in prefix_human
        assert "AGENT CONSENSUS via voting" in prefix_human

        # Autonomous mode should mention consensus for all
        assert "consensus" in prefix_autonomous.lower()


class TestTaskPlanningConfigValidation:
    """Test config validation for plan_depth."""

    def test_valid_plan_depths(self):
        """Test that valid plan_depth values pass validation."""
        from massgen.config_validator import ConfigValidator

        validator = ConfigValidator()

        for depth in ["shallow", "medium", "deep"]:
            config = {
                "orchestrator": {
                    "coordination": {
                        "plan_depth": depth,
                    },
                },
                "agents": [{"type": "claude", "model": "claude-sonnet-4-20250514"}],
            }
            result = validator.validate_config(config)
            # Should not have errors related to plan_depth
            plan_depth_errors = [e for e in result.errors if "plan_depth" in str(e)]
            assert len(plan_depth_errors) == 0, f"Unexpected error for depth '{depth}': {plan_depth_errors}"

    def test_invalid_plan_depth(self):
        """Test that invalid plan_depth value fails validation."""
        from massgen.config_validator import ConfigValidator

        validator = ConfigValidator()

        config = {
            "orchestrator": {
                "coordination": {
                    "plan_depth": "invalid_depth",
                },
            },
            "agents": [{"type": "claude", "model": "claude-sonnet-4-20250514"}],
        }
        result = validator.validate_config(config)

        # Should have an error about plan_depth
        plan_depth_errors = [e for e in result.errors if "plan_depth" in str(e)]
        assert len(plan_depth_errors) > 0, "Expected validation error for invalid plan_depth"


class TestCoordinationConfigPlanDepth:
    """Test CoordinationConfig plan_depth field."""

    def test_coordination_config_has_plan_depth(self):
        """Test that CoordinationConfig has plan_depth field."""
        from massgen.agent_config import CoordinationConfig

        config = CoordinationConfig()
        assert hasattr(config, "plan_depth")
        assert config.plan_depth is None  # Default is None

    def test_coordination_config_plan_depth_can_be_set(self):
        """Test that plan_depth can be set on CoordinationConfig."""
        from massgen.agent_config import CoordinationConfig

        config = CoordinationConfig(plan_depth="deep")
        assert config.plan_depth == "deep"
