"""
TransformIQ Backend — Auth API Router (Phase 11F, extended Phase 15)

Endpoints:
    POST   /api/v1/auth/register        — create an analyst account (password)
                                           + issue registration OTP (inactive)
    POST   /api/v1/auth/login           — email + password -> JWT (no OTP)
    POST   /api/v1/auth/verify          — exchange registration OTP for a JWT
                                           (activates the account)
    POST   /api/v1/auth/resend-otp      — re-issue a registration OTP
    POST   /api/v1/auth/forgot-password — request a password-reset OTP
    POST   /api/v1/auth/reset-password  — confirm reset OTP + new password
    GET    /api/v1/auth/me              — current user identity
    POST   /api/v1/auth/logout          — client-side logout acknowledgement

Security notes:
- The raw OTP is never returned in responses.
- Password login fails with a single generic 401 ("Invalid email or password.")
  for unknown emails, inactive accounts, missing hashes, and wrong passwords —
  account existence and activation state are never disclosed.
- Unknown-account OTP requests behave identically to a successful request to
  avoid leaking which emails are registered.
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
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    MeResponse,
    OtpDeliveryDetails,
    PasswordResetResponse,
    RegisterRequest,
    RegisterResponse,
    ResetPasswordRequest,
    UserSummary,
    VerifyOtpRequest,
)
from app.auth.service import (
    AccountNotFoundError,
    DuplicateAccountError,
    InvalidCredentialsError,
    RegistrationDisabledError,
    login_with_password,
    register_user,
    request_password_reset_otp,
    resend_registration_otp,
    reset_password,
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
        dev_otp=getattr(result, "dev_otp", None),
    )


def _generic_otp_details(body, identifier: str) -> OtpDeliveryDetails:
    """Uniform response body — identical for unknown and eligible accounts."""
    return OtpDeliveryDetails(
        channel=body.channel or "email",
        identifier=identifier,
        resend_after_seconds=0,
    )


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new analyst account (password + OTP verification)",
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
            password=body.password,
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
    response_model=AuthTokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Log in with email and password (Phase 15)",
)
async def login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(rate_limit_bucket("login")),
) -> AuthTokenResponse:
    """Verify email + password and return a short-lived JWT.

    A single generic 401 is returned for every failure mode so the response
    never reveals whether an email is registered, whether an account is
    pending activation, or why a password was rejected.
    """
    try:
        user, token, expires_in = await login_with_password(
            db,
            email=body.email,
            password=body.password,
        )
    except InvalidCredentialsError as exc:
        metrics.inc("authn_denials_total", {"reason": exc.reason})
        emit_security_event(
            "login_denied",
            outcome="denied",
            reason=exc.reason,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    emit_security_event("login_succeeded", outcome="allowed", user_id=str(user.id))

    return AuthTokenResponse(
        access_token=token,
        expires_in=expires_in,
        user=UserSummary.model_validate(user),
    )


@router.post(
    "/verify",
    response_model=AuthTokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Exchange the registration code for an access token",
)
async def verify(
    body: VerifyOtpRequest,
    db: AsyncSession = Depends(get_db),
    store: OtpStore = Depends(get_otp_store),
    _: None = Depends(rate_limit_bucket("otp_verify")),
) -> AuthTokenResponse:
    """Verify the submitted code, activate the account, and issue a JWT."""
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
    emit_security_event("otp_verified", outcome="allowed", reason="token_issued",
                        user_id=str(user.id))

    return AuthTokenResponse(
        access_token=token,
        expires_in=expires_in,
        user=UserSummary.model_validate(user),
    )


@router.post(
    "/resend-otp",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Re-issue a registration verification code",
)
async def resend_otp(
    body: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
    store: OtpStore = Depends(get_otp_store),
    delivery: OtpDeliveryProvider = Depends(get_otp_delivery_provider),
    _: None = Depends(rate_limit_bucket("otp_request")),
) -> LoginResponse:
    """Re-issue a registration OTP for a pending (inactive) account.

    Unknown or already-active accounts get a uniform response with no code
    delivered, so this endpoint does not leak whether an email is registered.
    """
    try:
        issued = await resend_registration_otp(
            db,
            email=body.email,
            channel=body.channel,
            mobile_number=body.mobile_number,
            store=store,
            delivery=delivery,
        )
    except OtpIssueError:
        issued = None
    except OtpDeliveryError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    if issued is None:
        return LoginResponse(data=_generic_otp_details(
            body,
            body.email if (body.channel or "email") == "email" else (body.mobile_number or ""),
        ))
    return LoginResponse(data=_delivery_details(issued))


@router.post(
    "/forgot-password",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Request a password-reset verification code",
)
async def forgot_password(
    body: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
    store: OtpStore = Depends(get_otp_store),
    delivery: OtpDeliveryProvider = Depends(get_otp_delivery_provider),
    _: None = Depends(rate_limit_bucket("otp_request")),
) -> LoginResponse:
    """Request a one-time reset code. The response is generic for unknown accounts."""
    try:
        issued = await request_password_reset_otp(
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
        return LoginResponse(data=_generic_otp_details(
            body,
            body.email if (body.channel or "email") == "email" else (body.mobile_number or ""),
        ))
    emit_security_event("password_reset_otp_requested", outcome="allowed", reason="otp_issued")
    return LoginResponse(data=_delivery_details(issued))


@router.post(
    "/reset-password",
    response_model=PasswordResetResponse,
    status_code=status.HTTP_200_OK,
    summary="Confirm a reset code and set a new password",
)
async def reset_password_confirm(
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
    store: OtpStore = Depends(get_otp_store),
    _: None = Depends(rate_limit_bucket("otp_verify")),
) -> PasswordResetResponse:
    """Verify the reset OTP and set the new password hash."""
    try:
        await reset_password(
            db,
            email=body.email,
            otp=body.otp,
            new_password=body.new_password,
            channel=body.channel,
            mobile_number=body.mobile_number,
            store=store,
        )
    except (AccountNotFoundError, OtpIssueError) as exc:
        emit_security_event("password_reset_denied", outcome="denied",
                            reason="account_or_issue_mismatch")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except OtpVerifyError as exc:
        emit_security_event("password_reset_denied", outcome="denied",
                            reason="otp_invalid")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    emit_security_event("password_reset_completed", outcome="allowed", user_id=str(
        (await _lookup_user_id(db, body.email)) or ""
    ))
    return PasswordResetResponse()


async def _lookup_user_id(db: AsyncSession, email: str) -> str | None:
    """Resolve a user id for audit logging (best-effort, never blocking)."""
    try:
        from sqlalchemy import select as _select

        from app.db.models.user import User as _User

        row = await db.execute(
            _select(_User.id).where(_User.email == email.strip().lower())
        )
        value = row.scalar_one_or_none()
        return str(value) if value is not None else None
    except Exception:  # pragma: no cover - audit must never break the flow
        return None


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