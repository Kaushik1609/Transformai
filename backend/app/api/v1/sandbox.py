"""
KaryaSetu AI — Sandbox Isolation API Router.

Provides operators, judges, and services endpoints to:
1. Query the agent sandbox isolation posture (Docker vs. Fallback).
2. Execute real-time security containment probes (verifying non-root, read-only root, etc.).
3. Safely execute agent tasks inside isolated sandboxes.
"""
from fastapi import APIRouter, HTTPException
import uuid

from app.sandbox import (
    SandboxExecutionResult,
    SandboxStatusResponse,
    SandboxTaskRequest,
    sandbox_runner,
)

router = APIRouter(prefix="/sandbox", tags=["Agent Sandbox Isolation"])


@router.get("/status", response_model=SandboxStatusResponse)
async def get_sandbox_status():
    """Return the operational and security posture of the agent sandbox engine."""
    return sandbox_runner.get_status()


@router.post("/probe", response_model=SandboxExecutionResult)
async def execute_security_probe():
    """
    Run an active zero-trust security probe inside the sandbox.
    Verifies that root filesystem writes are rejected and that user is non-root.
    """
    probe_task = SandboxTaskRequest(
        task_id=f"probe-{uuid.uuid4().hex[:8]}",
        task_type="probe_test",
        payload={"action": "verify_containment"},
        timeout_seconds=15,
    )
    result = sandbox_runner.run_task(probe_task)
    return result


@router.post("/execute", response_model=SandboxExecutionResult)
async def execute_sandboxed_task(request: SandboxTaskRequest):
    """Execute a task inside the agent sandbox."""
    try:
        return sandbox_runner.run_task(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Sandbox execution failed: {str(exc)}")
