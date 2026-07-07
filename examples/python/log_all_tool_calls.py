"""Audit every Strands tool call in Contro1 without pausing the agent."""

from __future__ import annotations

import os
from typing import Any

from centcom import CentcomClient
from strands import Agent
from strands.hooks import AfterToolCallEvent


client = CentcomClient(api_key=os.environ["CENTCOM_API_KEY"])


def _compact(value: Any, limit: int = 1200) -> str:
    text = repr(value)
    return text if len(text) <= limit else text[:limit] + "...[truncated]"


def log_tool_call(event: AfterToolCallEvent) -> None:
    """Hook for Agent(..., hooks=[log_tool_call])."""
    tool_name = event.tool_use["name"]
    run_id = event.invocation_state.get("run_id", os.getenv("STRANDS_RUN_ID", "strands-run"))
    result = event.result
    outcome = "failure" if isinstance(result, Exception) else "success"

    client.log_action(
        action=f"strands.tool.{tool_name}",
        summary=f"Strands tool completed: {tool_name}",
        source={"integration": "strands", "workflow_id": "agent", "run_id": run_id},
        outcome=outcome,
        severity="warning" if outcome == "failure" else "info",
        correlation_id=run_id,
        external_request_id=f"strands:{run_id}:{tool_name}",
        metadata={
            "framework": "strands-agents",
            "tool_name": tool_name,
            "tool_input": event.tool_use.get("input", {}),
            "result_summary": _compact(result),
        },
    )


# Wire this into your existing agent.
agent = Agent(
    tools=[],  # replace with your Strands tools
    hooks=[log_tool_call],
)
