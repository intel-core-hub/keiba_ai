"""Read-only control-plane status API.

This process must not import or mutate execution runtime state. Live decisions
belong to the execution process; this API only reports static operational
posture for operators and monitors.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import uvicorn
from fastapi import FastAPI

app = FastAPI(
    title="Keiba AI Control Plane",
    version="1.0.0",
    description="Read-only monitoring surface",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _status_payload() -> dict[str, Any]:
    return {
        "status": "READ_ONLY",
        "runtime_mutation": False,
        "decision_control": "execution_process_only",
        "timestamp": _utc_now(),
    }


@app.get("/")
def root() -> dict[str, Any]:
    return _status_payload()


@app.get("/health")
def health() -> dict[str, Any]:
    payload = _status_payload()
    payload["healthy"] = True
    return payload


@app.get("/status")
def status() -> dict[str, Any]:
    return _status_payload()


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
