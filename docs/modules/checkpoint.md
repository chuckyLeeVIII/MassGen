# Checkpoint Coordination Mode

Checkpoint mode enables a **delegator pattern** where a single main agent plans and gathers context solo, then delegates execution to the full team via the `checkpoint()` tool. After the team reaches consensus, the main agent resumes with the results.

## Architecture

### Mode Switching Lifecycle

```
Solo Mode                    Checkpoint Mode                 Solo Mode (resumed)
┌─────────┐  checkpoint()   ┌───────────────────┐  consensus  ┌─────────────┐
│ Main     │ ──────────────→ │ Fresh Agent A     │ ──────────→ │ Main Agent  │
│ Agent    │                 │ Fresh Agent B     │             │ (resumed)   │
│ (solo)   │                 │ ... iterate/vote  │             │ + results   │
└─────────┘                  └───────────────────┘             └─────────────┘
```

1. **Solo mode**: Only the main agent runs. It receives the `checkpoint` MCP tool.
2. **Checkpoint activation**: Main agent calls `checkpoint(task, eval_criteria, ...)`. Orchestrator:
   - Saves the main agent's session (paused, not destroyed)
   - Creates **fresh agent instances** with clean backends and cloned workspaces
   - Runs standard coordination (iterate, evaluate, vote) with the fresh agents
3. **Checkpoint completion**: Consensus reached. Orchestrator:
   - Copies deliverable files from the winning agent's workspace to the main agent's workspace
   - Destroys fresh agents
   - Restores the main agent's original session
   - Injects checkpoint results so the main agent can continue

### Why Fresh Instances

Participants are created as **brand-new agent objects** — new backends, empty conversation history, cloned workspaces. This provides:

- **Context isolation**: Pre-checkpoint reasoning doesn't bias participant work
- **Clean state**: No SDK session carry-over, no stale tool results
- **Separate logging**: Each participant gets its own log directory (`agent_a-ckpt1/`)

The alternative (reusing existing agents) was rejected because the Claude Code SDK session carries pre-checkpoint reasoning into the checkpoint round, and all snapshots/logs blend into the same directory regardless of phase.

### Why Clone Workspace (Not Empty)

Participants inherit the main agent's workspace files because the main agent may have set up context files (CONTEXT.md, configs, scaffolding) that participants need.

### Why Resume Original Session (Not Fresh)

After checkpoint, the main agent resumes its original session so it retains its planning context and can continue where it left off.

## Checkpoint Tool Schema

The `checkpoint()` tool accepts:

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| `task` | Yes | `string` | What agents should accomplish |
| `eval_criteria` | Yes | `list[string]` | Evaluation criteria for the checkpoint round |
| `context` | No | `string` | Background info, prior work |
| `personas` | No | `dict[string, string]` | Agent role assignments `{agent_id: persona_text}` |
| `gated_actions` | No | `list[dict]` | Restricted tools agents should propose rather than execute |

## Configuration

### YAML Config

```yaml
agents:
  - id: architect
    main_agent: true  # This agent delegates via checkpoint
    backend:
      type: claude
      model: claude-sonnet-4-20250514
  - id: builder_a
    backend:
      type: claude
      model: claude-sonnet-4-20250514
  - id: builder_b
    backend:
      type: openai
      model: gpt-4o

orchestrator:
  coordination:
    checkpoint_enabled: true
    checkpoint_mode: conversation  # or "task"
    checkpoint_gated_patterns:
      - "mcp__vercel__deploy*"  # Tools that should be proposed, not executed
```

- `main_agent: true` on an agent makes it the delegator (defaults to first agent if omitted)
- `checkpoint_enabled: true` activates checkpoint coordination
- `checkpoint_mode`: `conversation` (maintain context) or `task` (fresh per checkpoint)
- `checkpoint_gated_patterns`: fnmatch patterns for tools participants should propose rather than execute directly

## Execution Flow

1. Main agent runs solo, plans, gathers context
2. Main agent calls `checkpoint(task="Build the website", eval_criteria=["Clean code", "Responsive"])`
3. Orchestrator saves main agent state (session paused, not destroyed)
4. Fresh agent instances created — new backends, cloned workspaces, no history
5. Checkpoint coordination round runs (iterate, evaluate, vote)
6. Consensus reached — winning workspace files copied back to main agent
7. Fresh agents destroyed, main agent session resumed with results
8. Main agent continues solo with checkpoint deliverables in workspace

## WebUI Behavior

- Initially shows only the main agent channel
- On checkpoint: new channels appear for each participant (`agent_a-ckpt1`, `agent_b-ckpt1`)
- Main agent channel shows delegation notice, stops showing "Generating"
- Checkpoint tool call renders as a styled delegation card (not raw MCP tool name)
- After checkpoint: completion notice added to main agent channel

## Log Structure

```
log_session_dir/
  agent_a/                    # Main agent's pre-checkpoint work
    20260323_130655/
    workspace -> /workspace_abc123
  agent_a-ckpt1/             # Fresh checkpoint participant
    20260323_130720/
    workspace -> /workspace_abc123_ckpt_1_a1b2
  agent_b-ckpt1/             # Fresh checkpoint participant
    20260323_130720/
    workspace -> /workspace_abc123_ckpt_1_c3d4
  agent_outputs/
    main.txt                  # Pre-checkpoint delegator output
    agent_a-ckpt1.txt        # Checkpoint participant output
    agent_b-ckpt1.txt
```

## Implementation Details

### Key Files

| File | Role |
|------|------|
| `massgen/orchestrator.py` | `_activate_checkpoint()`, `_deactivate_checkpoint()`, `_create_fresh_checkpoint_agents()`, state save/restore |
| `massgen/cli.py` | `create_backend()` stamps `_backend_type` for recreation |
| `massgen/mcp_tools/checkpoint/` | Checkpoint MCP server, signal file I/O |
| `massgen/tool/workflow_toolkits/checkpoint.py` | Checkpoint tool schema definition |
| `massgen/frontend/agent_output_writer.py` | `main.txt` separation, participant file creation |
| `massgen/events.py` | `checkpoint_activated` / `checkpoint_completed` event types |

### Backend Type Stamping

`create_backend()` stamps `backend._backend_type = "type_string"` on every backend it creates. This enables `_create_fresh_checkpoint_agents()` to recreate backends without reverse-mapping from provider names.

### State Save/Restore

During checkpoint activation:
- `_save_pre_checkpoint_state()` saves: `agents`, `agent_states`, `coordination_tracker`, `workflow_tools`
- After checkpoint completes, `_restore_post_checkpoint_state()` restores all four

### Workspace Propagation

After checkpoint consensus, `_propagate_checkpoint_results_to_main_workspace()` copies non-hidden files from the winning participant's workspace to the main agent's workspace. This ensures deliverables are available when the main agent resumes.

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| Fresh instances (not session reuse) | Context isolation prevents pre-checkpoint reasoning from biasing participant work |
| Clone workspace (not empty) | Participants need files the main agent set up |
| Resume original session (not fresh) | Main agent needs its planning context to continue |
| In-process (not subprocess) | Live WebUI streaming; subprocess would show blank channels |
| Stamp backend type at creation | Reliable recreation without reverse-mapping provider names |
