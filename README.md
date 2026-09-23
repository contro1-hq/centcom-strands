# centcom-strands

Contro1 approval and audit patterns for [Strands Agents](https://strandsagents.com/) applications.

Use this connector guide when a Strands agent needs:

- human approval before risky tool calls,
- audit-only records for autonomous tool calls,
- signed callbacks before production actions resume,
- Control Map routing previews for high-risk roles, quorum, or SLA workflows,
- evidence exports that show what the agent asked, who decided, and what happened next.

This first version is a skill and examples repo. It uses the official Contro1 Python SDK and API directly; there is no Strands-specific package to install.

<!-- contro1:connect:start - generated from contro1.com/docs/connect-an-agent -->
## Connect your Strands agent to Contro1

A Strands agent runs in your own code, so it connects with an Agent Credential: a key bound to one agent, so every call is attributed to it and nothing in a request can change which agent it is.

1. Register the agent: contro1 init --name "<name>" --framework strands, and finish the setup link it prints (purpose and owner).
2. Connect the application account under Apps, if it is not connected yet.
3. Give the agent the Actions it needs under Access. It starts with none.
4. Create an Agent Credential for it (Settings, API keys) and store it as CONTRO1_API_KEY in your secret manager.
5. Call Actions from your tools as below. The same credential creates approval requests for work your own code does.

Full guide: [Connect an agent: every path, in full](https://contro1.com/docs/connect-an-agent)

### Run an application Action from a Strands tool

Contro1 holds the account and makes the call, so the record is what Contro1 observed. The tool returns what the Action produced; when a person has to approve first, it waits and then returns the result. It never re-submits: a retry could send a second email.

Before writing the input, read the exact input_schema with get_action_contract, or from the Action on the Access page.

Install: `pip install "centcom>=1.5.0"`

```python
import os, uuid
from centcom import CentcomClient, needs_human_resolution

contro1 = CentcomClient(api_key=os.environ["CONTRO1_API_KEY"])  # an Agent Credential

def run_action(action_id: str, input: dict, *, account_mode: str = "shared", **kw):
    """Run a Contro1 Action and return what it produced. Never retries a send."""
    out = contro1.actions.invoke(
        action_id, input,
        authority_mode=kw.pop("authority_mode", "agent_principal"),
        account_mode=account_mode,
        idempotency_key=kw.pop("idempotency_key", str(uuid.uuid4())),
        **kw,
    )
    inv = out["invocation"]
    if inv["state"] == "executed":
        return out["result"]
    if inv["state"] == "awaiting_approval":
        settled = contro1.actions.wait_for_invocation(inv["invocation_id"])
        if needs_human_resolution(settled):
            raise RuntimeError("Outcome unknown; a person must check. Do not retry.")
        return contro1.actions.get_result(settled["invocation_id"])
    raise RuntimeError(f"Not run: {inv['state']} {out.get('not_run', '')}")

from strands import Agent, tool

@tool
def list_recent_emails(max_results: int = 5) -> list:
    """List the most recent emails in the team mailbox."""
    return run_action("gmail.message.list", {"max_results": max_results})

agent = Agent(tools=[list_recent_emails])
```

Everything below this section covers the other half: asking a person before a step your own code runs, using the same credential. The helpers below read it as `CENTCOM_API_KEY`: that is the same Agent Credential under its older name.

<!-- contro1:connect:end -->

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
contro1 agents register --name "Production Strands Agent" --type strands
```

## Patterns

### 1. Simple approval before a risky tool

Start here. If one operator or one simple role can approve the action, you do not need Control Map first.
This example gives the Strands agent WRITE capability, but pauses before the production write. The reviewer sees the target service, environment, requested change, reason, and enough context to approve or reject before anything is written.

```python
import os
from strands import tool
from centcom import CentcomClient

client = CentcomClient(api_key=os.environ["CENTCOM_API_KEY"])

@tool
def write_production_config(service: str, key: str, value: str, reason: str) -> dict:
    run_id = os.getenv("STRANDS_RUN_ID", f"prod-write:{service}:{key}")
    request = client.create_protocol_request({
        "title": f"Approve production WRITE to {service}?",
        "request_type": "approval",
        "correlation_id": run_id,
        "external_request_id": f"strands:{run_id}:write_production_config",
        "source": {"integration": "strands", "framework": "strands-agents"},
        "routing": {"required_role": "production-operator", "priority": "urgent"},
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
        "continuation": {"mode": "decision", "webhook_url": os.environ["CENTCOM_CALLBACK_URL"]},
    })
    decision = client.wait_for_protocol_response(request["id"], timeout=600)
    if decision["status"] != "approved":
        raise PermissionError("Production WRITE rejected by operator")
    return production_api.update_config(service=service, key=key, value=value)
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

agent = Agent(tools=[search_docs, write_production_config], hooks=[log_tool_call])
```

### 3. Preview routing with Control Map

Use Control Map when high-risk approvals, quorum approvals, required roles, separation of duties, or SLA/fallback workflows need a routing preview. Do not use it for every low-risk read/search/list action.

```bash
contro1 requests control-map \
  --role finance \
  --required-approvals 2 \
  --approval-role finance \
  --must-include-role cfo \
  --risk high \
  --reason "Payment exceeds autonomous limit"
```

If the preview is not satisfiable, treat it as routing context, not a denial; show `warnings` or `suggested_action` and let the approval request remain the gate.

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
