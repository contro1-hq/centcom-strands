"""Optional Control Map preview before high-risk Strands approvals."""

from __future__ import annotations

import os
from typing import Any

import httpx
from centcom import CentcomClient
from strands import tool


BASE_URL = os.getenv("CENTCOM_BASE_URL", "https://api.contro1.com/api/centcom/v1")
client = CentcomClient(api_key=os.environ["CENTCOM_API_KEY"], base_url=BASE_URL)


def preview_finance_routing() -> dict[str, Any]:
    """Use only when routing/quorum certainty matters."""
    response = httpx.post(
        f"{BASE_URL}/requests/control-map",
        headers={
            "Authorization": f"Bearer {os.environ['CENTCOM_API_KEY']}",
            "Content-Type": "application/json",
        },
        json={
            "type": "approval",
            "question": "Preview finance approval routing",
            "context": "High-risk Strands payment tool",
            "required_role": "finance",
            "risk_level": "high",
            "policy_trigger": "Payments above $10,000 require finance approval and CFO review.",
            "approval_requirements": {
                "required_roles": ["finance"],
                "required_approvals": 2,
                "must_include_roles": ["cfo"],
            },
            "approval_policy": {
                "mode": "threshold",
                "required_approvals": 2,
                "required_roles": ["finance", "cfo"],
                "separation_of_duties": True,
                "fail_closed_on_timeout": True,
            },
        },
        timeout=15,
    )
    response.raise_for_status()
    preview = response.json()
    if not preview.get("satisfiable"):
        raise RuntimeError(f"Routing not ready: {preview.get('warnings') or preview.get('suggested_action')}")
    return preview


@tool
def send_vendor_payment(vendor_id: str, amount_usd: float) -> dict[str, Any]:
    """Preview routing, then ask for approval, then execute payment."""
    run_id = os.getenv("STRANDS_RUN_ID", f"payment:{vendor_id}")
    preview_finance_routing()

    request = client.create_protocol_request(
        {
            "title": f"Approve ${amount_usd:.2f} payment to {vendor_id}?",
            "request_type": "approval",
            "correlation_id": run_id,
            "external_request_id": f"strands:{run_id}:send_vendor_payment",
            "source": {"integration": "strands", "framework": "strands-agents", "run_id": run_id},
            "routing": {"required_role": "finance", "priority": "urgent", "sla_minutes": 10},
            "context": {
                "tool_name": "send_vendor_payment",
                "tool_input": {"vendor_id": vendor_id, "amount_usd": amount_usd},
                "action_type": "payment",
            },
            "risk_level": "high",
            "policy_trigger": "Payments above $10,000 require finance approval and CFO review.",
            "approval_comment_required": True,
            "approval_requirements": {
                "required_roles": ["finance"],
                "required_approvals": 2,
                "must_include_roles": ["cfo"],
            },
            "approval_policy": {
                "mode": "threshold",
                "required_approvals": 2,
                "required_roles": ["finance", "cfo"],
                "separation_of_duties": True,
                "fail_closed_on_timeout": True,
            },
            "continuation": {"mode": "decision", "webhook_url": os.environ["CENTCOM_CALLBACK_URL"]},
        }
    )
    decision = client.wait_for_protocol_response(request["id"], timeout=900)
    if decision["status"] != "approved":
        raise PermissionError(decision.get("message") or "Payment rejected by operator")
    return {"status": "paid", "vendor_id": vendor_id, "amount_usd": amount_usd}
