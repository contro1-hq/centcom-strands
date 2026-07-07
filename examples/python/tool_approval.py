"""Simple Contro1 approval before a risky Strands production WRITE executes."""

from __future__ import annotations

import os
from typing import Any

from centcom import CentcomClient
from strands import tool


client = CentcomClient(api_key=os.environ["CENTCOM_API_KEY"])


def _write_production_config(service: str, key: str, value: str) -> dict[str, Any]:
    """Replace with your production config, database, or server WRITE client."""
    return {"status": "written", "service": service, "key": key}


@tool
def write_production_config(service: str, key: str, value: str, reason: str) -> dict[str, Any]:
    """Write to production only after Contro1 approval."""
    run_id = os.getenv("STRANDS_RUN_ID", f"prod-write:{service}:{key}")
    request = client.create_protocol_request(
        {
            "title": f"Approve production WRITE to {service}?",
            "request_type": "approval",
            "correlation_id": run_id,
            "external_request_id": f"strands:{run_id}:write_production_config",
            "source": {"integration": "strands", "framework": "strands-agents", "run_id": run_id},
            "routing": {"required_role": "production-operator", "priority": "urgent"},
            "actor": {
                "agent_id": os.getenv("CENTCOM_AGENT_ID", ""),
                "agent_name": "Strands production agent",
            },
            "context": {
                "tool_name": "write_production_config",
                "tool_input": {"service": service, "key": key, "value_preview": value[:200]},
                "action_type": "production_write",
                "environment": "production",
                "target": f"service:{service}",
                "requested_write": {
                    "operation": "update_config",
                    "service": service,
                    "key": key,
                    "value_preview": value[:200],
                },
                "summary": reason,
            },
            "continuation": {
                "mode": "decision",
                "webhook_url": os.environ["CENTCOM_CALLBACK_URL"],
            },
        }
    )

    decision = client.wait_for_protocol_response(request["id"], timeout=600)
    if decision["status"] != "approved":
        raise PermissionError(decision.get("message") or "Production WRITE rejected by operator")

    result = _write_production_config(service, key, value)
    client.log_action(
        action="strands.production_write_completed",
        summary=f"Wrote {key} to production service {service} after approval",
        source={"integration": "strands", "workflow_id": "production-agent", "run_id": run_id},
        outcome="success",
        correlation_id=run_id,
        in_reply_to={"type": "request", "id": request["id"]},
        metadata={"service": service, "key": key},
    )
    return result
