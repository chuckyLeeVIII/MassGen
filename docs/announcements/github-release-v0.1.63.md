# 🚀 Release Highlights — v0.1.63 (2026-03-13)

### 🎯 [Ensemble Pattern](https://docs.massgen.ai/en/latest/user_guide/concepts.html#multi-agent-coordination)
- **Ensemble defaults for subagents**: `disable_injection` and `defer_voting_until_all_answered` now default to true, so subagents work independently before voting for more diverse, higher-quality results
- **Automatic ensemble orchestration**: Defaults apply when spawning subagent orchestrators without explicit override

### 🔄 [Round Evaluator Improvements](https://docs.massgen.ai/en/latest/reference/yaml_schema.html)
- **Transformation pressure**: Evaluator pushes agents toward meaningful structural changes rather than surface-level edits
- **Success contracts**: Explicit quality gates agents must satisfy before the round evaluator allows convergence
- **Verification replay**: Evaluation consistency across rounds via replayed verification context

### ⚡ [Lighter Refinement](https://docs.massgen.ai/en/latest/user_guide/concepts.html)
- **Reduced subagent overhead**: Lighter refinement prompts for subagent workflows cut token usage and latency
- **Killed agent handling**: Graceful management of agents that time out or fail mid-round

### ✅ Fixes
- **Timeout fallback**: More robust coordination when agents hit timeout boundaries

---

### 📖 Getting Started
- [**Quick Start Guide**](https://github.com/massgen/MassGen?tab=readme-ov-file#1--installation)
- **Try It**:
  ```bash
  pip install massgen==0.1.63
  # Try the round evaluator with ensemble defaults
  uv run massgen --config @examples/features/round_evaluator_example.yaml "Create a polished landing page for an AI product"
  ```
