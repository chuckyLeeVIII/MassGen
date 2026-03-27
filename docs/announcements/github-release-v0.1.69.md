# 🚀 Release Highlights — v0.1.69 (2026-03-27)

### 🌐 [WebUI Automation Auto-Start](https://docs.massgen.ai/en/latest/user_guide/webui.html)
- **Auto-start without browser interaction**: `massgen --web --automation --config config.yaml "Your question"` begins immediately — open the URL at any point to monitor progress mid-run
- **Full CLI flags with `--web`**: `--eval-criteria`, `--checklist-criteria-preset`, and `--orchestrator-timeout` now work when combined with `--web`
- **Automatic config resolution**: Automation mode resolves config automatically when none is specified

### 🤖 [MassGen Skill in WebUI](https://docs.massgen.ai/en/latest/user_guide/skills.html)
- **Skill runs in WebUI** ([#1032](https://github.com/massgen/MassGen/pull/1032)): MassGen skill launches directly from the WebUI with live session tracking and monitoring
- **Auto-end on completion**: Web automation correctly auto-ends when a skill completes

### ✨ Enhancements
- **Gemini CLI provider** ([#1032](https://github.com/massgen/MassGen/pull/1032)): New `gemini_cli` backend support
- **Flexible criteria fields** ([#1032](https://github.com/massgen/MassGen/pull/1032)): `description` or `name` accepted as alternatives to `text` in evaluation criteria JSON
- **UI polish**: Improved round view, top banner, modal refinements, and frontend quickstart flow

---

### 📖 Getting Started
- [**Quick Start Guide**](https://github.com/massgen/MassGen?tab=readme-ov-file#1--installation)
- **Try It**:
  ```bash
  pip install massgen==0.1.69
  # Auto-start a run and monitor in the WebUI
  uv run massgen --web --automation --config config.yaml "Your question"
  ```
