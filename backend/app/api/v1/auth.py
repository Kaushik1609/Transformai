"""
TransformIQ Backend — Auth API Router (Phase 11F)

Endpoints:
    POST   /api/v1/auth/register   — create an analyst account + issue OTP
    POST   /api/v1/auth/login      — request an OTP for an existing account
    POST   /api/v1/auth/verify     — exchange an OTP for a JWT
    GET    /api/v1/auth/me         — current user identity
    POST   /api/v1/auth/logout     — client-side logout acknowledgement

Security notes:
- The raw OTP is never returned in responses.
- Unknown-account login behaves identically to a successful request to avoid
  leaking which emails are registered.
- All entrypoints are individually rate limited (IP-based).
"""
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_current_user
from app.auth.otp_delivery import OtpDeliveryError, OtpDeliveryProvider, get_otp_delivery_provider
from app.auth.otp_service import OtpIssueError, OtpVerifyError
from app.auth.otp_store import OtpStore, get_otp_store
from app.auth.schemas import (
    AuthTokenResponse,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    MeResponse,
    OtpDeliveryDetails,
    RegisterRequest,
    RegisterResponse,
    UserSummary,
    VerifyOtpRequest,
)
from app.auth.service import (
    AccountNotFoundError,
    DuplicateAccountError,
    RegistrationDisabledError,
    register_user,
    request_login_otp,
    verify_login,
)
from app.core.audit import emit_security_event
from app.core.metrics import metrics
from app.core.ratelimit import rate_limit_bucket
from app.core.token_revocation import get_revocation_store, revoke_access_token
from app.db.session import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def _extract_bearer(request: Request) -> str | None:
    """Extract the raw bearer credential for server-side revocation."""
    header = request.headers.get("Authorization", "")
    scheme, _, credentials = header.partition(" ")
    if scheme.lower() not in {"bearer", "token"} or not credentials.strip():
        return None
    return credentials.strip()


def _delivery_details(result) -> OtpDeliveryDetails:
    return OtpDeliveryDetails(
        channel=result.channel,
        identifier=result.identifier,
        resend_after_seconds=result.resend_after_seconds,
    )


def _generic_login_details(body: LoginRequest) -> OtpDeliveryDetails:
    """Uniform response body — identical for unknown accounts and throttled logins."""
    identifier = (
        body.mobile_number
        if (body.channel or "email") == "mobile"
        else body.email
    )
    return OtpDeliveryDetails(
        channel=body.channel or "email",
        identifier=identifier,
        resend_after_seconds=0,
    )


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new analyst account (OTP verification)",
)
async def register(
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
    store: OtpStore = Depends(get_otp_store),
    delivery: OtpDeliveryProvider = Depends(get_otp_delivery_provider),
    _: None = Depends(rate_limit_bucket("otp_request")),
) -> RegisterResponse:
    """Create a new analyst account and deliver a verification code."""
    try:
        _user, issued = await register_user(
            db,
            name=body.name,
            email=body.email,
            mobile_number=body.mobile_number,
            channel=body.channel,
            store=store,
            delivery=delivery,
        )
        emit_security_event("account_registered", outcome="allowed")
    except RegistrationDisabledError as exc:
        emit_security_event("account_registration_declined", outcome="denied",
                            reason="registration_disabled")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except DuplicateAccountError as exc:
        emit_security_event("account_registration_declined", outcome="denied",
                            reason="duplicate_account")
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except OtpIssueError as exc:
        emit_security_event("otp_issue_limited", outcome="denied", reason="quota_exceeded")
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    except OtpDeliveryError as exc:
        emit_security_event("otp_delivery_failed", outcome="denied", reason="delivery_error")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return RegisterResponse(data=_delivery_details(issued))


@router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Request an OTP for an existing account",
)
async def login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
    store: OtpStore = Depends(get_otp_store),
    delivery: OtpDeliveryProvider = Depends(get_otp_delivery_provider),
    _: None = Depends(rate_limit_bucket("login")),
) -> LoginResponse:
    """Request a one-time code. The response is generic for unknown accounts."""
    try:
        issued = await request_login_otp(
            db,
            email=body.email,
            channel=body.channel,
            mobile_number=body.mobile_number,
            store=store,
            delivery=delivery,
        )
    except OtpIssueError:
        # Keep the response identical to the unknown-account case (cooldown /
        # per-window quota must not reveal whether an account exists).
        issued = None
    except OtpDeliveryError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    if issued is None:
        return LoginResponse(data=_generic_login_details(body))
    emit_security_event("otp_requested", outcome="allowed", reason="otp_issued")
    return LoginResponse(data=_delivery_details(issued))


@router.post(
    "/verify",
    response_model=AuthTokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Exchange a one-time code for an access token",
)
async def verify(
    body: VerifyOtpRequest,
    db: AsyncSession = Depends(get_db),
    store: OtpStore = Depends(get_otp_store),
    _: None = Depends(rate_limit_bucket("otp_verify")),
) -> AuthTokenResponse:
    """Verify the submitted code and issue a short-lived JWT on success."""
    try:
        user, token, expires_in = await verify_login(
            db,
            email=body.email,
            channel=body.channel,
            otp=body.otp,
            mobile_number=body.mobile_number,
            store=store,
        )
    except (AccountNotFoundError, OtpIssueError) as exc:
        emit_security_event("otp_verification_denied", outcome="denied",
                            reason="account_or_issue_mismatch")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except OtpVerifyError as exc:
        emit_security_event("otp_verification_denied", outcome="denied",
                            reason="otp_invalid")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    emit_security_event("otp_verified", outcome="allowed", reason="token_issued")

    return AuthTokenResponse(
        access_token=token,
        expires_in=expires_in,
        user=UserSummary.model_validate(user),
    )


@router.get(
    "/me",
    response_model=MeResponse,
    summary="Return the authenticated user's identity",
)
async def me(
    current_user: CurrentUser = Depends(get_current_user),
) -> MeResponse:
    return MeResponse(
        data=UserSummary(
            id=current_user.id,
            email=current_user.email,
            name=current_user.name,
            role=current_user.role,
        )
    )


@router.post(
    "/logout",
    response_model=LogoutResponse,
    summary="Revoke the presented token server-side (Phase 13A)",
)
async def logout(
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    store=Depends(get_revocation_store),
) -> LogoutResponse:
    """Revoke the presented access token so it cannot be replayed.

    The token's ``jti`` is registered in the revocation store until the token
    would expire. A token that is already revoked, malformed, or missing a
    ``jti`` is handled idempotently — logout always succeeds because the client
    discards its local copy regardless.
    """
    token = _extract_bearer(request)
    revoked = (
        revoke_access_token(token, store=store)
        if token is not None
        else False
    )
    result = (
        "revoked" if revoked else "no_jti"
        if token is not None else "missing_token"
    )
    metrics.inc("token_revoked_total", {"result": result})
    emit_security_event(
        "logout",
        outcome="allowed",
        user_id=str(current_user.id),
        reason="token_revoked" if revoked else "client_side_only",
    )
    logger.info("auth_logout", user_id=str(current_user.id), revoked=revoked)
    return LogoutResponse()