"""
KaryaSetu AI — Sandbox Isolation Schemas
Data models for agent sandbox configurations, execution tasks, and containment results.
"""
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class SandboxSecurityProfile(BaseModel):
    """Zero-trust security constraints applied to agent execution."""
    network_mode: str = Field(default="none", description="Container network isolation mode ('none' for air-gapped).")
    memory_limit: str = Field(default="512m", description="Max memory allowed before OOM kill.")
    cpu_quota: float = Field(default=1.0, description="Max CPU cores allocated to sandbox.")
    read_only_root: bool = Field(default=True, description="Mount root filesystem as read-only.")
    cap_drop: List[str] = Field(default_factory=lambda: ["ALL"], description="Linux capabilities stripped.")
    non_root_user: str = Field(default="1000:1000", description="UID:GID for non-privileged execution.")
    no_new_privileges: bool = Field(default=True, description="Prevent privilege escalation via setuid/setgid.")
    tmpfs_size: str = Field(default="64m", description="Bounded ephemeral scratchpad size.")


class SandboxTaskRequest(BaseModel):
    """Payload sent to an agent inside the sandbox."""
    task_id: str
    task_type: str = Field(
        default="probe_test",
        description="Type or name of agent to execute (e.g. summary_agent, linkedin_agent, parse, etc.)"
    )
    payload: Dict[str, Any]
    timeout_seconds: int = Field(default=60, ge=1, le=300)
    security_profile: Optional[SandboxSecurityProfile] = None


class SandboxExecutionResult(BaseModel):
    """Result and cryptographic audit verification of sandbox execution."""
    task_id: str
    status: Literal["success", "error", "timeout", "killed"]
    execution_mode: Literal["docker_sandbox", "subsystem_fallback"]
    exit_code: int
    duration_ms: float
    output: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    security_audit: Dict[str, Any] = Field(
        default_factory=dict,
        description="Audit trace of security constraints verified during execution."
    )


class SandboxStatusResponse(BaseModel):
    """Status of the sandbox isolation engine."""
    docker_available: bool
    docker_version: Optional[str] = None
    default_mode: Literal["docker_sandbox", "subsystem_fallback"]
    isolation_features: List[str]
    active_sandboxes: int = 0
