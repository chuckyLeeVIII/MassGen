# MassGen v0.1.63 Release Announcement

<!--
This is the current release announcement. Copy this + feature-highlights.md to LinkedIn/X.
After posting, update the social links below.
-->

## Release Summary

We're excited to release MassGen v0.1.63 — Round Evaluator Contracts! 🚀 MassGen now supports improved critique and toggling the level of changes in the round evaluator, with transformation pressure and success contracts for deeper quality. Plus: subagents run as an ensemble by default with lighter refinement, and killed agent handling.

## Install

```bash
pip install massgen==0.1.63
```

## Links

- **Release notes:** https://github.com/massgen/MassGen/releases/tag/v0.1.63
- **X post:** [TO BE ADDED AFTER POSTING]
- **LinkedIn post:** [TO BE ADDED AFTER POSTING]

---

## Full Announcement (for LinkedIn)

Copy everything below this line, then append content from `feature-highlights.md`:

---

We're excited to release MassGen v0.1.63 — Round Evaluator Contracts! 🚀 MassGen now supports improved critique and toggling the level of changes in the round evaluator, with transformation pressure and success contracts for deeper quality. Plus: subagents run as an ensemble by default with lighter refinement, and killed agent handling.

**Key Improvement:**

🔄 **Round Evaluator Contracts** - Improved critique with configurable transformation levels:
- Transformation pressure pushes agents toward meaningful structural changes rather than surface edits
- Success contracts define explicit quality gates agents must satisfy before convergence
- Verification replay ensures evaluation consistency across rounds

**Plus:**
- 🎯 **Subagent ensemble by default** — `disable_injection` and `defer_voting_until_all_answered` default to true, subagents work independently with lighter refinement before voting
- 🛡️ **Killed agent handling** — graceful management of agents that time out or fail mid-round
- 🔧 **Timeout fallback** — more robust coordination at timeout boundaries

**Getting Started:**

```bash
pip install massgen==0.1.63
# Try the round evaluator with ensemble defaults
uv run massgen --config @examples/features/round_evaluator_example.yaml "Create a polished landing page for an AI product"
```

Release notes: https://github.com/massgen/MassGen/releases/tag/v0.1.63

Feature highlights:

<!-- Paste feature-highlights.md content here -->
