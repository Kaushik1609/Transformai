"""TransformIQ Backend — Auth Service Package (Phase 11F)."""

from app.auth.otp_delivery import (
    EmailOtpProvider,
    OtpDeliveryProvider,
    ResendOtpProvider,
)
from app.auth.otp_service import (
    OtpIssueError,
    OtpIssueResult,
    OtpVerifyError,
    issue_otp,
    verify_otp,
)
from app.auth.otp_store import (
    MemoryOtpStore,
    OtpRecord,
    OtpStore,
    RedisOtpStore,
    get_otp_store,
)
from app.auth.schemas import (
    AdminUserSummary,
    AuthTokenResponse,
    LoginRequest,
    MeResponse,
    OtpDeliveryDetails,
    RegisterRequest,
    RegisterResponse,
    UserSummary,
    VerifyOtpRequest,
)

__all__ = [
    # Delivery
    "EmailOtpProvider",
    "OtpDeliveryProvider",
    "ResendOtpProvider",
    # OTP service
    "OtpIssueError",
    "OtpIssueResult",
    "OtpVerifyError",
    "issue_otp",
    "verify_otp",
    # Store
    "MemoryOtpStore",
    "OtpRecord",
    "OtpStore",
    "RedisOtpStore",
    "get_otp_store",
    # Schemas
    "AdminUserSummary",
    "AuthTokenResponse",
    "LoginRequest",
    "MeResponse",
    "OtpDeliveryDetails",
    "RegisterRequest",
    "RegisterResponse",
    "UserSummary",
    "VerifyOtpRequest",
]