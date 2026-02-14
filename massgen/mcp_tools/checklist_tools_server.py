# -*- coding: utf-8 -*-
"""Standalone MCP server that exposes the MassGen submit_checklist tool.

This allows CLI-based backends (Codex) to use the checklist-gated voting
tool as a native MCP tool call.  The server reads checklist configuration
and mutable state from a JSON specs file written by the orchestrator.

The server re-reads the specs file on every tool call so the orchestrator
can update state (remaining budget, has_existing_answers) between rounds
without restarting the server process.

Usage (launched by backend via config.toml):
    fastmcp run massgen/mcp_tools/checklist_tools_server.py:create_server -- \
        --specs /path/to/checklist_specs.json
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any, Dict

import fastmcp

logger = logging.getLogger(__name__)

SERVER_NAME = "massgen_checklist"


async def create_server() -> fastmcp.FastMCP:
    """Factory function to create MCP server from checklist specs."""
    parser = argparse.ArgumentParser(description="MassGen Checklist MCP Server")
    parser.add_argument(
        "--specs",
        type=str,
        required=True,
        help="Path to JSON file containing checklist specs and state",
    )
    args = parser.parse_args()

    mcp = fastmcp.FastMCP(SERVER_NAME)
    specs_path = Path(args.specs)

    _register_checklist_tool(mcp, specs_path)

    logger.info(f"Checklist MCP server ready (specs: {specs_path})")
    return mcp


def _read_specs(specs_path: Path) -> Dict[str, Any]:
    """Read specs file, returning empty dict on error."""
    try:
        with open(specs_path) as f:
            return json.load(f)
    except Exception as exc:
        logger.error(f"Failed to read checklist specs: {exc}")
        return {}


def _extract_score(entry: Any) -> int:
    """Extract numeric score from either int or {"score": int, "reasoning": str}."""
    if isinstance(entry, dict):
        return entry.get("score", 0)
    if isinstance(entry, (int, float)):
        return int(entry)
    return 0


def _resolve_report_file(report_path: str, state: Dict[str, Any]) -> tuple[Path | None, str | None]:
    """Resolve report path to a workspace-local absolute path."""
    raw_path = (report_path or "").strip()
    if not raw_path:
        return None, "Missing `report_path`."

    workspace_root = state.get("workspace_path")
    workspace = Path(workspace_root).resolve() if workspace_root else Path.cwd().resolve()
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = (workspace / candidate).resolve()
    else:
        candidate = candidate.resolve()

    try:
        candidate.relative_to(workspace)
    except ValueError:
        return None, f"Report path must stay inside workspace ({workspace})."

    return candidate, None


def _evaluate_gap_report(report_path: str, state: Dict[str, Any]) -> Dict[str, Any]:
    """Check gap report file existence for diagnostics (no gate logic).

    The gap report is informational only — it never overrides the checklist verdict.
    Basic file existence and non-empty checks are retained for transparency in the
    explanation, but no heuristic scoring or keyword matching is performed.
    """
    result: Dict[str, Any] = {
        "provided": bool((report_path or "").strip()),
        "path": (report_path or "").strip(),
        "passed": True,  # Always passes — no gate
        "issues": [],
    }

    if not result["provided"]:
        return result

    resolved, error = _resolve_report_file(report_path, state)
    if error:
        result["issues"].append(error)
        return result
    if resolved is None:
        return result

    result["resolved_path"] = str(resolved)
    if not resolved.exists():
        result["issues"].append(f"Report file not found: {resolved}")
        return result
    if not resolved.is_file():
        result["issues"].append(f"Report path is not a file: {resolved}")
        return result

    try:
        report_text = resolved.read_text(encoding="utf-8")
    except Exception as exc:
        result["issues"].append(f"Unable to read report file: {exc}")
        return result

    if not report_text.strip():
        result["issues"].append("Report file is empty.")
        return result

    # Report exists and is non-empty — note it for transparency
    result["file_exists"] = True
    return result


def evaluate_checklist_submission(
    scores: Dict[str, Any],
    improvements: str,
    report_path: str,
    items: list,
    state: Dict[str, Any],
) -> Dict[str, Any]:
    """Evaluate checklist submission and return verdict payload used by stdio + SDK."""
    if not isinstance(scores, dict):
        scores = {}

    terminate_action = state.get("terminate_action", "vote")
    iterate_action = state.get("iterate_action", "new_answer")
    has_existing_answers = state.get("has_existing_answers", False)
    required = state.get("required", len(items))
    cutoff = state.get("cutoff", 70)

    items_detail = []
    true_count = 0
    for i, _item_text in enumerate(items):
        key = f"T{i+1}"
        entry = scores.get(key, 0)
        score = _extract_score(entry)
        passed = score >= cutoff
        if passed:
            true_count += 1
        items_detail.append({"id": key, "score": score, "passed": passed})

    report_eval = _evaluate_gap_report(report_path, state)

    if not has_existing_answers:
        verdict = iterate_action
        explanation = f"First answer — no existing answers to evaluate. Verdict: {verdict}."
    else:
        # Verdict determined solely by T1-T5 scores — no report gate
        verdict = terminate_action if true_count >= required else iterate_action

        if verdict == iterate_action:
            failed_ids = [d["id"] for d in items_detail if not d["passed"]]
            improvements_text = improvements.strip() if improvements else ""
            explanation = f"{true_count} of {len(items)} items passed (required: {required}). " f"Verdict: {verdict}. "
            if failed_ids:
                explanation += f"Items that need improvement: {', '.join(failed_ids)}. "
            explanation += "Your new answer MUST make material changes — do NOT simply copy or " "resubmit the same content."
            if improvements_text:
                explanation += (
                    f" Your own improvements analysis identified: {improvements_text} "
                    f"— use this as your implementation plan. The result must be "
                    f"obviously better, not just marginally different."
                )
        else:
            explanation = f"{true_count} of {len(items)} items passed (required: {required}). " f"Verdict: {verdict}."

    # Include report diagnostics for transparency (informational only)
    if report_eval.get("provided"):
        report_summary = " Gap report provided."
        if report_eval.get("issues"):
            report_summary += f" Report notes: {'; '.join(report_eval['issues'])}."
        explanation += report_summary

    return {
        "verdict": verdict,
        "explanation": explanation,
        "true_count": true_count,
        "required": required,
        "items": items_detail,
        "report": report_eval,
        "report_gate_triggered": False,
    }


def _register_checklist_tool(mcp: fastmcp.FastMCP, specs_path: Path) -> None:
    """Register the submit_checklist tool on the FastMCP server."""
    import inspect

    # Read specs once at startup just for the tool schema
    specs = _read_specs(specs_path)
    items = specs.get("items", [])

    # Create handler that re-reads state on each call.
    # Each score entry is {"score": int, "reasoning": str} — the reasoning
    # forces the model to justify each item but is not used in verdict logic.
    # `improvements` captures unrealized potential.
    async def submit_checklist(
        scores: dict,
        improvements: str = "",
        report_path: str = "",
    ) -> str:
        # Codex sometimes sends scores as a JSON string; normalise to dict
        if isinstance(scores, str):
            try:
                scores = json.loads(scores)
            except (json.JSONDecodeError, TypeError):
                return json.dumps(
                    {"error": "scores must be a JSON object, not a string"},
                )
        if not isinstance(scores, dict):
            return json.dumps(
                {"error": "scores must be a JSON object"},
            )

        # Re-read specs to get latest state from orchestrator
        current = _read_specs(specs_path)
        current_items = current.get("items", items)
        state = current.get("state", {})
        result = evaluate_checklist_submission(
            scores=scores,
            improvements=improvements,
            report_path=report_path,
            items=current_items,
            state=state,
        )
        return json.dumps(result)

    submit_checklist.__doc__ = (
        "Submit your checklist evaluation. Each score in 'scores' must be an "
        "object with 'score' (0-100) and 'reasoning' (why you gave that score). "
        "The 'improvements' field should describe features or content that an "
        "ideal answer would have but no existing answer has attempted. "
        "Use 'report_path' to provide a markdown gap report when report gating "
        "is enabled."
    )

    # Set proper signature so FastMCP sees both parameters
    sig = inspect.Signature(
        [
            inspect.Parameter("scores", inspect.Parameter.POSITIONAL_OR_KEYWORD),
            inspect.Parameter("improvements", inspect.Parameter.POSITIONAL_OR_KEYWORD),
            inspect.Parameter("report_path", inspect.Parameter.POSITIONAL_OR_KEYWORD),
        ],
    )
    submit_checklist.__signature__ = sig

    mcp.tool(
        name="submit_checklist",
        description=submit_checklist.__doc__,
    )(submit_checklist)

    logger.info("Registered submit_checklist MCP tool")


# ---------- spec file I/O ----------


def write_checklist_specs(
    items: list,
    state: Dict[str, Any],
    output_path: Path,
) -> Path:
    """Write checklist specs + state to a JSON file.

    Called by the orchestrator before launch and whenever state changes.
    """
    specs = {
        "items": items,
        "state": state,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        # State may include pathlib objects (for example workspace paths)
        # that need string normalization for JSON transport.
        json.dump(specs, f, indent=2, default=str)
    return output_path


def build_server_config(specs_path: Path) -> Dict[str, Any]:
    """Build a stdio MCP server config dict for the checklist server."""
    script_path = Path(__file__).resolve()

    return {
        "name": SERVER_NAME,
        "type": "stdio",
        "command": "fastmcp",
        "args": [
            "run",
            f"{script_path}:create_server",
            "--",
            "--specs",
            str(specs_path),
        ],
        "env": {"FASTMCP_SHOW_CLI_BANNER": "false"},
        "tool_timeout_sec": 120,
    }
