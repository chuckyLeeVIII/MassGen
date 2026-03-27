# MassGen v0.1.69 Release Announcement

<!--
This is the current release announcement. Copy this + feature-highlights.md to LinkedIn/X.
After posting, update the social links below.
-->

## Release Summary

We're excited to release MassGen v0.1.69 — WebUI Automation & Skill Mode! 🚀 The WebUI now auto-starts coordination runs without browser interaction, CLI flags (`--eval-criteria`, `--checklist-criteria-preset`, `--orchestrator-timeout`) work with `--web`, the MassGen skill runs natively in the WebUI, and the new `gemini_cli` provider is supported.

## Install

```bash
pip install massgen==0.1.69
```

## Links

- **Release notes:** https://github.com/massgen/MassGen/releases/tag/v0.1.69
- **X post:** [TO BE ADDED AFTER POSTING]
- **LinkedIn post:** [TO BE ADDED AFTER POSTING]

---

## Full Announcement (for LinkedIn)

Copy everything below this line, then append content from `feature-highlights.md`:

---

We're excited to release MassGen v0.1.69 — WebUI Automation & Skill Mode! 🚀 The WebUI now auto-starts coordination runs without browser interaction. Open the URL at any point mid-run to monitor progress. Plus: CLI flags work with `--web`, the MassGen skill runs natively in the WebUI, and Gemini CLI provider support.

**Key Improvements:**

🌐 **WebUI Automation Auto-Start** — No browser interaction needed to kick off a run:
- `massgen --web --automation --config config.yaml "Your question"` starts immediately
- Open http://localhost:8000 at any point to monitor a live run
- Web automation correctly auto-ends when a skill completes

🔧 **CLI Flags with `--web`** — Full flag support for web-monitored runs:
- `--eval-criteria`, `--checklist-criteria-preset`, `--orchestrator-timeout` now work with `--web`
- Automatic config resolution when no config is specified

🤖 **MassGen Skill in WebUI** — Run the MassGen skill directly from the WebUI:
- Skills launch with live session tracking
- Monitor skill progress through the full WebUI interface

**Plus:**
- ✨ **Gemini CLI provider** — New `gemini_cli` backend support
- 📋 **Flexible criteria fields** — `description` or `name` accepted as alternatives to `text` in criteria JSON
- 🎨 **UI polish** — Improved round view, top banner, modal refinements, and quickstart flow

**Getting Started:**

```bash
pip install massgen==0.1.69
# Auto-start a run and watch in WebUI
uv run massgen --web --automation --config config.yaml "Your question"
```

Release notes: https://github.com/massgen/MassGen/releases/tag/v0.1.69

Feature highlights:

<!-- Paste feature-highlights.md content here -->
