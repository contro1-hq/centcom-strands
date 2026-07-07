"""FastAPI receiver for signed Contro1 callbacks."""

from __future__ import annotations

import os
from typing import Any

from centcom import verify_webhook
from fastapi import FastAPI, Request, Response


app = FastAPI()

# Replace with a durable store keyed by request_id in production.
DECISIONS: dict[str, dict[str, Any]] = {}


@app.post("/webhooks/contro1")
async def contro1_webhook(request: Request) -> Response:
    raw_body = await request.body()
    signature = request.headers.get("X-CentCom-Signature", "")
    timestamp = request.headers.get("X-CentCom-Timestamp", "")
    request_id = request.headers.get("X-CentCom-Request-Id", "")

    if not verify_webhook(raw_body, signature, timestamp, os.environ["CENTCOM_WEBHOOK_SECRET"]):
        return Response("invalid signature", status_code=401)

    payload = await request.json()
    status = payload.get("status") or payload.get("state")
    response = payload.get("response") or {}

    if status in {"cancelled", "expired"}:
        DECISIONS[request_id] = {"status": status, "approved": False, "payload": payload}
        return Response("ok", status_code=200)

    DECISIONS[request_id] = {
        "status": "answered",
        "approved": bool(response.get("approved")),
        "payload": payload,
    }
    return Response("ok", status_code=200)
