---
name: centcom-strands
description: Add Contro1 approval gates, Control Map routing previews, signed callbacks, and audit-only action logging to Strands Agents projects.
user_invocable: true
---

# Contro1 + Strands Agents Skill

Use this skill when integrating Contro1 into a Strands Agents codebase.

## Goal

Add a clear operational control layer without rewriting the Strands app:

- log every autonomous tool call that should be visible in Contro1,
- require human approval before risky tools execute,
- use Control Map only when routing, quorum, SLA, or fallback certainty matters,
- verify signed webhooks before production actions resume,
- keep Bedrock, AgentCore, Guardrails, memory, and observability configuration intact.

## Inspect The Codebase First

Find:

- `Agent(...)` construction.
- `tools=[...]` passed to the agent.
- `@tool` functions and tool wrappers.
- existing `hooks=[...]`.
- existing `interventions=[...]`, especially Strands `HumanInTheLoop`.
- model provider setup, including `BedrockModel`.
- deployment entrypoint for local server, AgentCore Runtime, Lambda, container, or API server.
- any session, run, thread, trace, or request id already available.

Do not replace the agent framework or model provider. Add Contro1 around tool execution and action logging.

## Classify Tools

Audit-only tools usually run autonomously and should be logged:

- read,
- search,
- list,
- classify,
- summarize,
- retrieve,
- inspect,
- draft without sending.

Approval-required tools must pause before execution:

- send customer or external messages,
- payments, refunds, payouts, invoices,
- production WRITE operations to servers, databases, configs, feature flags, or infrastructure,
- production deploys or migrations,
- deletes or irreversible updates,
- permission changes,
- CRM, billing, auth, HR, finance, or production database writes,
- high-volume changes,
- actions with high/critical risk.

When unsure, start with a small explicit risk map instead of asking the model to infer policy.

## Pattern 1: Log Every Tool Call

Use Strands `AfterToolCallEvent` for audit-only visibility. This does not pause the agent.

```python
import os
from centcom import CentcomClient
from strands import Agent
from strands.hooks import AfterToolCallEvent

client = CentcomClient(api_key=os.environ["CENTCOM_API_KEY"])

def log_tool_call(event: AfterToolCallEvent):
    run_id = event.invocation_state.get("run_id", "strands-run")
    tool_name = event.tool_use["name"]
    client.log_action(
        action=f"strands.tool.{tool_name}",
        summary=f"Strands tool completed: {tool_name}",
        source={"integration": "strands", "workflow_id": "agent", "run_id": run_id},
        outcome="success",
        correlation_id=run_id,
        external_request_id=f"strands:{run_id}:{tool_name}",
        metadata={
            "framework": "strands-agents",
            "tool_name": tool_name,
            "tool_input": event.tool_use.get("input", {}),
        },
    )

agent = Agent(tools=tools, hooks=[log_tool_call])
```

Redact secrets, tokens, PII, long documents, and full retrieved context. Store compact summaries unless the customer explicitly wants raw fields.

## Pattern 2: Simple Approval First

For one operator or simple role routing, create a request before the risky action. Do not add Control Map until it is useful.
For production WRITE, the agent can hold the capability, but the tool must pause before execution. Put the full reviewer context in the request: exact target, environment, requested change, reason, expected impact, rollback notes when available, and compact/redacted inputs.

```python
import os
from centcom import CentcomClient
from strands import tool

client = CentcomClient(api_key=os.environ["CENTCOM_API_KEY"])

@tool
def write_production_config(service: str, key: str, value: str, reason: str) -> dict:
    run_id = os.getenv("STRANDS_RUN_ID", f"prod-write:{service}:{key}")
    request = client.create_protocol_request({
        "title": f"Approve production WRITE to {service}?",
        "request_type": "approval",
        "correlation_id": run_id,
        "external_request_id": f"strands:{run_id}:write_production_config",
        "source": {"integration": "strands", "framework": "strands-agents", "run_id": run_id},
        "routing": {"required_role": "production-operator", "priority": "urgent"},
        "actor": {"agent_id": os.getenv("CENTCOM_AGENT_ID", ""), "agent_name": "Strands production agent"},
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
        raise PermissionError(decision.get("message") or "Production WRITE rejected by operator")

    result = production_api.update_config(service=service, key=key, value=value)
    client.log_action(
        action="strands.production_write_completed",
        summary=f"Wrote {key} to production service {service} after approval",
        source={"integration": "strands", "workflow_id": "production-agent", "run_id": run_id},
        outcome="success",
        correlation_id=run_id,
        in_reply_to={"type": "request", "id": request["id"]},
    )
    return result
```

Polling is acceptable for local demos. Production systems should prefer signed webhooks or a durable decision store.

## Pattern 3: BeforeToolCallEvent Approval Gate

Use this when you want one central hook for named risky tools.

```python
from strands.hooks import BeforeToolCallEvent

RISKY_TOOLS = {"write_production_config", "run_sql_write", "issue_refund", "update_crm", "deploy_release"}

def approve_risky_tool(event: BeforeToolCallEvent):
    tool_name = event.tool_use["name"]
    if tool_name not in RISKY_TOOLS:
        return
    run_id = event.invocation_state.get("run_id", "strands-run")
    request = client.create_protocol_request({
        "title": f"Approve Strands tool: {tool_name}?",
        "request_type": "approval",
        "correlation_id": run_id,
        "external_request_id": f"strands:{run_id}:{tool_name}",
        "source": {"integration": "strands", "framework": "strands-agents", "run_id": run_id},
        "routing": {"required_role": "manager"},
        "context": {"tool_name": tool_name, "tool_input": event.tool_use.get("input", {})},
        "continuation": {"mode": "decision", "webhook_url": os.environ["CENTCOM_CALLBACK_URL"]},
    })
    decision = client.wait_for_protocol_response(request["id"], timeout=600)
    if decision["status"] != "approved":
        event.cancel_tool = decision.get("message") or "Tool rejected by operator"
```

If the project already uses Strands `HumanInTheLoop`, adapt its ask/evaluate callback to create a Contro1 request and return approval only after the signed decision is valid.

## Pattern 4: Control Map Before Complex Approval

Use Control Map only when it helps:

- high or critical risk,
- required roles,
- two-person approval,
- separation of duties,
- SLA or fallback routing,
- production actions where waiting on an unroutable request is bad UX.

Do not call Control Map for every read/search/list action.

```python
import os
import httpx

BASE_URL = os.getenv("CENTCOM_BASE_URL", "https://api.contro1.com/api/centcom/v1")

def preview_finance_routing() -> dict:
    response = httpx.post(
        f"{BASE_URL}/requests/control-map",
        headers={
            "Authorization": f"Bearer {os.environ['CENTCOM_API_KEY']}",
            "Content-Type": "application/json",
        },
        json={
            "type": "approval",
            "question": "Preview finance approval routing",
            "context": "High-risk Strands finance tool",
            "required_role": "finance",
            "risk_level": "high",
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
```

Cache positive previews briefly by role/policy where appropriate. Still create a real approval request for the action.

## Pattern 5: Signed Webhook

Production webhook receivers must verify:

- `X-CentCom-Signature`,
- `X-CentCom-Timestamp`,
- `X-CentCom-Request-Id`.

Fail closed on:

- invalid signature,
- stale timestamp,
- denied,
- cancelled,
- timed_out,
- unknown request id,
- request id not matching the pending action.

```python
from centcom import verify_webhook

if not verify_webhook(raw_body, signature, timestamp, os.environ["CENTCOM_WEBHOOK_SECRET"]):
    return {"error": "invalid signature"}, 401
```

## Data Mapping

Use these fields consistently:

- `source.integration`: `strands`
- `source.framework`: `strands-agents`
- `correlation_id`: Strands run/session id.
- `thread_id`: `thr_...` when using Contro1 thread timelines.
- `external_request_id`: `strands:{run_id}:{tool_name}:{tool_use_id}`
- `context.tool_name`: Strands tool name.
- `context.tool_input`: compact/redacted input.
- `actor.agent_id`: registered Contro1 agent id if available.

Audit-only actions go to `/audit-records`. Approval-required actions go to `/requests`. Complex routing previews go to `/requests/control-map`.

## CLI Setup And Use Cases

Use the CLI when a developer, coding agent, CI job, or operator needs to test or operate the Strands integration without writing new code first.

The CLI is useful for:

- registering the Strands agent so requests and audit records are attributed to the right system,
- manually testing the approval path before wiring it into a Strands tool,
- previewing Control Map routing for high-risk role/quorum policies,
- pulling evidence and traces after an approval,
- using a scoped token in CI or a headless Strands runtime,
- gating a local command for demos, deploy scripts, or operational runbooks.

### 1. Sign in and inspect the workspace

```bash
contro1 auth login
contro1 whoami
contro1 doctor
```

For CI or a headless machine, use a scoped CLI token:

```bash
export CONTRO1_TOKEN=cco_cli_live_xxx
contro1 whoami --scopes
```

### 2. Register the Strands agent

Register once per meaningful agent/runtime. Store the returned `agent_id` in `CENTCOM_AGENT_ID` and pass it in approval/audit payloads.

```bash
contro1 agents register \
  --name "Production Strands Agent" \
  --type strands \
  --description "Strands agent using Contro1 approvals and audit logging"

contro1 agents list
contro1 agents get <agent_id>
```

### 3. Test a simple one-operator approval

Use this before editing Strands code. It proves API keys, routing, operator queue, decisions, and evidence work.

```bash
contro1 requests create \
  --type approval \
  --question "Approve this test production WRITE?" \
  --agent <agent_id> \
  --role production-operator \
  --risk high \
  --reason "Strands agent wants WRITE access to update production config" \
  --correlation-id strands-test-run-001 \
  --external-request-id strands:test-run-001:write_production_config \
  --wait
```

If this works, implement the same pattern inside the risky Strands `@tool` or `BeforeToolCallEvent` hook.

### 4. Preview Control Map only when routing matters

Use Control Map for high-risk, quorum, role-specific, SLA, fallback reviewer, or separation-of-duties workflows. Do not add it to low-risk autonomous read/search/list actions.

```bash
contro1 requests control-map \
  --role finance \
  --required-approvals 2 \
  --approval-role finance \
  --must-include-role cfo \
  --risk high \
  --reason "Payment exceeds autonomous limit" \
  --format json
```

If the preview is not satisfiable, fail closed in code and surface `warnings` or `suggested_action` to the admin/operator.

### 5. Pull evidence and traces

After the operator decides, pull the proof packet and run trail. This is useful for testing, incident review, and customer demos.

```bash
contro1 evidence for-request <request_id>
contro1 traces for-request <request_id>
contro1 agents trail <agent_id>
```

### 6. Optional: gate a local command

This is not the main Strands runtime pattern, but it is useful for demos, migrations, deploys, or scripts around the agent.

```bash
contro1 run \
  --agent <agent_id> \
  --role release-manager \
  --risk high \
  --reason "Deploying Strands approval bridge" \
  --requires-approval \
  -- npm run deploy
```

## Reference Links

- Contro1 Strands docs: https://contro1.com/docs/strands-agents-human-approval
- Repo: https://github.com/contro1-hq/centcom-strands
- Skill file source: https://github.com/contro1-hq/centcom-strands/blob/main/skills/centcom-strands.md
- Contro1 requests API: https://contro1.com/docs/requests-api
- Contro1 webhooks: https://contro1.com/docs/webhooks
- Strands Agents docs: https://strandsagents.com/
