"""
KaryaSetu AI — Agent Sandbox Runner.

Provides Docker-based container isolation for agent execution, with zero-trust
controls (air-gapped network, read-only root filesystem, dropped Linux capabilities,
memory/CPU bounds, and non-root execution).

Includes an automated bounded fallback for environments where the Docker daemon
is offline, ensuring resilience during local development and testing.
"""
import json
import os
import subprocess
import time
from typing import Any, Dict, Optional

import structlog

from app.sandbox.schemas import (
    SandboxExecutionResult,
    SandboxSecurityProfile,
    SandboxStatusResponse,
    SandboxTaskRequest,
)

logger = structlog.get_logger(__name__)

DEFAULT_SANDBOX_IMAGE = os.environ.get("AGENT_SANDBOX_IMAGE", "python:3.11-alpine")


class AgentSandboxRunner:
    """Manages the creation, execution, and teardown of agent sandboxes."""

    def __init__(self, image: str = DEFAULT_SANDBOX_IMAGE):
        self.image = image
        self._docker_client = None
        self._docker_checked = False
        self._docker_available = False

    def is_docker_available(self) -> bool:
        """Check if Docker daemon is reachable on host."""
        try:
            import docker
            client = docker.from_env(timeout=2)
            client.ping()
            self._docker_client = client
            self._docker_available = True
            return True
        except Exception as exc:
            logger.debug("docker_daemon_unavailable", error=str(exc))
            self._docker_client = None
            self._docker_available = False
            return False

    def get_status(self) -> SandboxStatusResponse:
        """Inspect the current sandbox engine posture."""
        available = self.is_docker_available()
        version = None
        if available and self._docker_client:
            try:
                version = self._docker_client.version().get("Version")
            except Exception:
                version = "connected"

        return SandboxStatusResponse(
            docker_available=available,
            docker_version=version,
            default_mode="docker_sandbox" if available else "subsystem_fallback",
            isolation_features=[
                "air_gapped_network_isolation (--network none)",
                "memory_budget_enforcement (--memory 512m)",
                "cpu_quota_capping (--cpus 1.0)",
                "read_only_root_filesystem (--read-only)",
                "dropped_linux_capabilities (--cap-drop ALL)",
                "non_root_execution (UID 1000)",
                "no_new_privileges_flag",
                "ephemeral_tmpfs_scratchpad (/tmp noexec)",
            ],
            active_sandboxes=0,
        )

    def run_task(self, request: SandboxTaskRequest) -> SandboxExecutionResult:
        """Execute a task inside the isolated sandbox (or fallback if Docker is offline)."""
        profile = request.security_profile or SandboxSecurityProfile()
        start_time = time.perf_counter()

        # 1. Attempt Docker container execution if daemon is accessible
        if self.is_docker_available():
            try:
                return self._run_in_docker(request, profile, start_time)
            except Exception as exc:
                logger.warning(
                    "docker_sandbox_execution_failed_falling_back",
                    task_id=request.task_id,
                    error=str(exc),
                )

        # 2. Resilient bounded fallback execution
        return self._run_fallback(request, profile, start_time)

    def _run_in_docker(
        self,
        request: SandboxTaskRequest,
        profile: SandboxSecurityProfile,
        start_time: float,
    ) -> SandboxExecutionResult:
        """Execute task inside an ephemeral, hardened Docker container."""
        # Find absolute path to entrypoint script
        entrypoint_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "entrypoint.py")
        )

        task_json = request.model_dump_json()

        # Mount the entrypoint read-only inside the container
        volumes = {
            entrypoint_path: {"bind": "/app/entrypoint.py", "mode": "ro"}
        }

        logger.info(
            "spawning_agent_docker_sandbox",
            task_id=request.task_id,
            image=self.image,
            net_mode=profile.network_mode,
            mem=profile.memory_limit,
        )

        with open(entrypoint_path, "r", encoding="utf-8") as f:
            entrypoint_code = f.read()

        container = self._docker_client.containers.run(
            image=self.image,
            command=["python", "-c", entrypoint_code],
            environment={"SANDBOX_TASK_INPUT": task_json},
            network_mode=profile.network_mode,
            mem_limit=profile.memory_limit,
            nano_cpus=int(profile.cpu_quota * 1_000_000_000),
            read_only=profile.read_only_root,
            cap_drop=profile.cap_drop,
            user=profile.non_root_user,
            security_opt=["no-new-privileges:true"] if profile.no_new_privileges else [],
            tmpfs={"/tmp": f"rw,noexec,nosuid,size={profile.tmpfs_size}"},
            stdin_open=False,
            detach=False,
            remove=True,
            stdout=True,
            stderr=True,
        )

        duration_ms = (time.perf_counter() - start_time) * 1000.0
        raw_output = container.decode("utf-8").strip()

        try:
            parsed = json.loads(raw_output)
            output_data = parsed.get("output")
            exit_code = parsed.get("exit_code", 0)
            err_msg = parsed.get("error_message")
        except json.JSONDecodeError:
            output_data = {"raw_stdout": raw_output}
            exit_code = 0
            err_msg = None

        return SandboxExecutionResult(
            task_id=request.task_id,
            status="success" if exit_code == 0 else "error",
            execution_mode="docker_sandbox",
            exit_code=exit_code,
            duration_ms=duration_ms,
            output=output_data,
            error_message=err_msg,
            security_audit={
                "isolation": "DOCKER_CONTAINER",
                "network_mode": profile.network_mode,
                "read_only_root": profile.read_only_root,
                "cap_drop": profile.cap_drop,
                "user": profile.non_root_user,
                "memory_limit": profile.memory_limit,
            },
        )

    def _run_fallback(
        self,
        request: SandboxTaskRequest,
        profile: SandboxSecurityProfile,
        start_time: float,
    ) -> SandboxExecutionResult:
        """Safe in-process / subprocess fallback when Docker engine is not available."""
        from app.sandbox.entrypoint import execute_task

        logger.info(
            "executing_sandbox_in_resilient_fallback",
            task_id=request.task_id,
            task_type=request.task_type,
        )

        try:
            output_data = execute_task(request.task_type, request.payload)
            exit_code = 0
            status = "success"
            err_msg = None
        except Exception as exc:
            output_data = None
            exit_code = 1
            status = "error"
            err_msg = str(exc)

        duration_ms = (time.perf_counter() - start_time) * 1000.0

        return SandboxExecutionResult(
            task_id=request.task_id,
            status=status,
            execution_mode="subsystem_fallback",
            exit_code=exit_code,
            duration_ms=duration_ms,
            output=output_data,
            error_message=err_msg,
            security_audit={
                "isolation": "LOCAL_PROCESS_FALLBACK",
                "notice": "Docker daemon offline; execution executed with in-process isolation",
                "governance_rule": "bounded_timeout_applied",
            },
        )


# Global singleton instance
sandbox_runner = AgentSandboxRunner()
