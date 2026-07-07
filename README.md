# centcom-strands

Contro1 approval and audit patterns for [Strands Agents](https://strandsagents.com/) applications.

Use this connector guide when a Strands agent needs:

- human approval before risky tool calls,
- audit-only records for autonomous tool calls,
- signed callbacks before production actions resume,
- Control Map routing previews for high-risk roles, quorum, or SLA workflows,
- evidence exports that show what the agent asked, who decided, and what happened next.

This first version is a skill and examples repo. It uses the official Contro1 Python SDK and API directly; there is no Strands-specific package to install.

## Install

```bash
pip install strands-agents centcom
```

For TypeScript Strands projects:

```bash
npm install @strands-agents/sdk @contro1/sdk
```

## Environment

```bash
CENTCOM_API_KEY=cc_live_your_key
CENTCOM_BASE_URL=https://api.contro1.com/api/centcom/v1
CENTCOM_WEBHOOK_SECRET=whsec_your_signing_secret
CENTCOM_CALLBACK_URL=https://your-app.example.com/webhooks/contro1
CENTCOM_AGENT_ID=agt_your_registered_agent
```

Register the agent with the CLI:

```bash
contro1 agents register --name "Support Strands Agent" --type strands
```

## Patterns

### 1. Simple approval before a risky tool

Start here. If one operator or one simple role can approve the action, you do not need Control Map first.

```python
from strands import tool
from centcom import CentcomClient

client = CentcomClient(api_key=os.environ["CENTCOM_API_KEY"])

@tool
def send_customer_email(customer_id: str, subject: str, body: str) -> dict:
    request = client.create_protocol_request({
        "title": f"Send email to {customer_id}?",
        "request_type": "approval",
        "source": {"integration": "strands", "framework": "strands-agents"},
        "routing": {"required_role": "support-manager"},
        "context": {
            "tool_name": "send_customer_email",
            "tool_input": {"customer_id": customer_id, "subject": subject},
            "summary": body[:500],
        },
        "continuation": {"mode": "decision", "webhook_url": os.environ["CENTCOM_CALLBACK_URL"]},
    })
    decision = client.wait_for_protocol_response(request["id"], timeout=600)
    if decision["status"] != "approved":
        raise PermissionError("Email rejected by operator")
    return email_api.send(customer_id, subject, body)
```

### 2. Log every autonomous tool call

Use Strands `AfterToolCallEvent` to send audit-only actions to Contro1. This does not pause the agent.

```python
from strands import Agent
from strands.hooks import AfterToolCallEvent

def log_tool_call(event: AfterToolCallEvent):
    client.log_action(
        action=f"strands.tool.{event.tool_use['name']}",
        summary=f"Strands tool completed: {event.tool_use['name']}",
        source={"integration": "strands", "workflow_id": "support-agent", "run_id": run_id},
        outcome="success",
        correlation_id=run_id,
        metadata={"tool_input": event.tool_use.get("input", {})},
    )

agent = Agent(tools=[search_docs, send_customer_email], hooks=[log_tool_call])
```

### 3. Preview routing with Control Map

Use Control Map before high-risk approvals, quorum approvals, required roles, separation of duties, or SLA/fallback workflows. Do not use it for every low-risk read/search/list action.

```bash
contro1 requests control-map \
  --role finance \
  --required-approvals 2 \
  --approval-role finance \
  --must-include-role cfo \
  --risk high \
  --reason "Payment exceeds autonomous limit"
```

If the preview is not satisfiable, fail closed and show `warnings` or `suggested_action` to the operator/admin.

### 4. Signed webhook handling

Production systems should verify Contro1 callback signatures before resuming a Strands action or marking a delayed action approved.

```python
from centcom import verify_webhook

if not verify_webhook(raw_body, signature, timestamp, os.environ["CENTCOM_WEBHOOK_SECRET"]):
    raise PermissionError("Invalid Contro1 webhook signature")
```

## Examples

- `examples/python/tool_approval.py` - simple one-operator approval before a risky tool.
- `examples/python/log_all_tool_calls.py` - audit-only logging for every Strands tool call.
- `examples/python/control_map_then_approval.py` - optional Control Map preview before high-risk approval.
- `examples/python/webhook_receiver.py` - signed callback verification.

## Documentation

- Contro1 Strands docs: https://contro1.com/docs/strands-agents-human-approval
- Contro1 requests API: https://contro1.com/docs/requests-api
- Contro1 webhooks: https://contro1.com/docs/webhooks
- Strands Agents docs: https://strandsagents.com/
