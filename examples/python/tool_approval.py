"""Simple Contro1 approval before a risky Strands tool executes."""

from __future__ import annotations

import os
from typing import Any

from centcom import CentcomClient
from strands import tool


client = CentcomClient(api_key=os.environ["CENTCOM_API_KEY"])


def _send_email(customer_id: str, subject: str, body: str) -> dict[str, Any]:
    """Replace with your email provider."""
    return {"status": "sent", "customer_id": customer_id, "subject": subject}


@tool
def send_customer_email(customer_id: str, subject: str, body: str) -> dict[str, Any]:
    """Send an email only after Contro1 approval."""
    run_id = os.getenv("STRANDS_RUN_ID", f"email:{customer_id}")
    request = client.create_protocol_request(
        {
            "title": f"Send email to {customer_id}?",
            "request_type": "approval",
            "correlation_id": run_id,
            "external_request_id": f"strands:{run_id}:send_customer_email",
            "source": {"integration": "strands", "framework": "strands-agents", "run_id": run_id},
            "routing": {"required_role": "support-manager", "priority": "normal"},
            "actor": {
                "agent_id": os.getenv("CENTCOM_AGENT_ID", ""),
                "agent_name": "Strands support agent",
            },
            "context": {
                "tool_name": "send_customer_email",
                "tool_input": {"customer_id": customer_id, "subject": subject},
                "action_type": "customer_message",
                "summary": body[:500],
            },
            "continuation": {
                "mode": "decision",
                "webhook_url": os.environ["CENTCOM_CALLBACK_URL"],
            },
        }
    )

    decision = client.wait_for_protocol_response(request["id"], timeout=600)
    if decision["status"] != "approved":
        raise PermissionError(decision.get("message") or "Email rejected by operator")

    result = _send_email(customer_id, subject, body)
    client.log_action(
        action="strands.email_sent",
        summary=f"Sent email to {customer_id} after approval",
        source={"integration": "strands", "workflow_id": "support-agent", "run_id": run_id},
        outcome="success",
        correlation_id=run_id,
        in_reply_to={"type": "request", "id": request["id"]},
        metadata={"subject": subject},
    )
    return result
