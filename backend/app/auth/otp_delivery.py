"""
TransformIQ Backend — OTP Delivery Providers (Phase 11F)

Abstraction over the channels an OTP can be delivered through:

- ``ConsoleOtpProvider``: logs the code to the structured log. The raw code is
  ONLY logged when ENVIRONMENT=development; production always logs a redacted
  marker. It also keeps the most recent code per (channel, identifier) so the
  offline/test flow can read the code it would receive.
- ``EmailOtpProvider``: SMTP delivery (config via SMTP_* env vars).
- ``SmsOtpProvider``: gateway delivery (config via SMS_* env vars).

Credentialed providers require their up-front configuration; they fail closed
(raise) rather than silently writing codes to the log. The factory falls back
to the Console provider only in development, never in production.
"""
from __future__ import annotations

import smtplib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Literal

import structlog
from fastapi import Request

from app.core.config import settings

logger = structlog.get_logger(__name__)

Channel = Literal["email", "mobile"]


class OtpDeliveryError(RuntimeError):
    """Raised when an OTP cannot be delivered."""


@dataclass(frozen=True)
class OtpDeliveryResult:
    delivered: bool
    channel: str
    identifier: str
    provider_name: str
    status: str = "delivered"  # "delivered" | "failed" | "unavailable"
    error_message: str | None = None
    otp: str | None = None


def _mask(identifier: str) -> str:
    """Mask an email/phone for logging: a***@e.co / +1***1234."""
    at = identifier.rfind("@")
    if at > 0:
        local, domain = identifier[:at], identifier[at:]
        kept = local[:1] if local else ""
        return f"{kept}{'*' * max(0, min(4, len(local) - 1))}{'*' if len(local) > 1 else ''}{domain}"
    digits = "".join(c for c in identifier if c.isdigit())
    if digits:
        return f"{'*' * max(0, len(digits) - 4)}{digits[-4:]}"
    return "*" * len(identifier)


class OtpDeliveryProvider(ABC):
    """Abstract OTP delivery channel.

    Designed for extension across delivery channels (Email, future Twilio SMS).
    """

    provider_name: str = "abstract"
    delivery_channel: str = "email"

    @abstractmethod
    def send_otp(
        self,
        *,
        channel: Channel,
        identifier: str,
        otp: str,
        reason: str = "authentication",
    ) -> OtpDeliveryResult: ...


class ConsoleOtpProvider(OtpDeliveryProvider):
    """Development/test provider. Logs redacted marker and keeps offline test seam."""

    provider_name = "console"
    delivery_channel = "email"

    def __init__(self) -> None:
        self.recent_codes: dict[tuple[str, str], str] = {}

    def send_otp(
        self,
        *,
        channel: Channel,
        identifier: str,
        otp: str,
        reason: str = "authentication",
    ) -> OtpDeliveryResult:
        # Test seam: record code in memory so offline test suites can read it via last_otp_for.
        self.recent_codes[(channel, identifier.strip().lower())] = otp
        logger.info(
            "otp_console_delivery",
            channel=channel,
            identifier=_mask(identifier),
            reason=reason,
            otp="[REDACTED]",
        )
        return OtpDeliveryResult(
            delivered=True,
            channel=channel,
            identifier=identifier,
            provider_name=self.provider_name,
            status="delivered",
            otp=None,
        )

    def last_otp_for(self, channel: Channel, identifier: str) -> str | None:
        return self.recent_codes.get((channel, identifier.strip().lower()))


class EmailOtpProvider(OtpDeliveryProvider):
    """SMTP email delivery. Requires SMTP_HOST, SMTP_USER, and SMTP_FROM to be configured."""

    provider_name = "email"
    delivery_channel = "email"

    def _require_config(self) -> None:
        missing = [
            name
            for name, value in (
                ("SMTP_HOST", settings.SMTP_HOST),
                ("SMTP_USER", settings.SMTP_USER),
                ("SMTP_FROM", settings.SMTP_FROM),
            )
            if not value
        ]
        if missing:
            raise OtpDeliveryError(
                f"Email OTP delivery requires {', '.join(missing)} to be configured."
            )

    def send_otp(
        self,
        *,
        channel: Channel,
        identifier: str,
        otp: str,
        reason: str = "authentication",
    ) -> OtpDeliveryResult:
        if channel != "email":
            raise OtpDeliveryError("EmailOtpProvider supports channel='email' only.")
        self._require_config()
        message = EmailMessage()
        message["Subject"] = f"TransformIQ verification code ({settings.SMTP_FROM_NAME})"
        message["From"] = (
            f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM}>"
        )
        message["To"] = identifier
        message.set_content(
            f"Your TransformIQ verification code is {otp}.\n"
            f"It expires in {settings.OTP_EXPIRY_SECONDS} seconds. "
            "If you did not request this, you can safely ignore this email."
        )
        delivered_via = self.provider_name
        delivered_otp = None
        try:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=5) as server:
                server.starttls()
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(message)
            logger.info("otp_email_delivered", identifier=_mask(identifier))
        except Exception as exc:
            logger.warning(
                "otp_email_delivery_failed",
                identifier=_mask(identifier),
                error=str(exc),
            )
            raise OtpDeliveryError(
                "We couldn't send the verification email. Please try again later."
            ) from exc

        return OtpDeliveryResult(
            delivered=True,
            channel="email",
            identifier=identifier,
            provider_name=self.provider_name,
            status="delivered",
            otp=None,
        )


class ResendOtpProvider(OtpDeliveryProvider):
    """Resend HTTP API email delivery.

    Delivers verification codes via the Resend HTTPS API (port 443),
    bypassing cloud provider blocks on outbound SMTP ports 25, 465, and 587.
    """

    provider_name = "resend"
    delivery_channel = "email"

    def __init__(self, api_key: str | None = None, from_address: str | None = None) -> None:
        self.api_key = (api_key or settings.RESEND_API_KEY or "").strip()
        self.from_address = (from_address or settings.RESEND_FROM or "TransformIQ <onboarding@resend.dev>").strip()

    def _require_config(self) -> None:
        if not self.api_key:
            raise OtpDeliveryError("Resend OTP delivery requires RESEND_API_KEY to be configured.")

    def send_otp(
        self,
        *,
        channel: Channel,
        identifier: str,
        otp: str,
        reason: str = "authentication",
    ) -> OtpDeliveryResult:
        if channel != "email":
            raise OtpDeliveryError("ResendOtpProvider supports channel='email' only.")
        self._require_config()

        subject = f"TransformIQ verification code ({settings.SMTP_FROM_NAME})"
        text_content = (
            f"Your TransformIQ verification code is {otp}.\n"
            f"It expires in {settings.OTP_EXPIRY_SECONDS} seconds.\n"
            "If you did not request this, you can safely ignore this email."
        )
        html_content = (
            f"<div style='font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, Helvetica, Arial, sans-serif; max-width: 480px; margin: 0 auto; padding: 24px; border: 1px solid #e2e8f0; border-radius: 8px;'>"
            f"<h2 style='color: #0f172a; margin-top: 0;'>TransformIQ Verification</h2>"
            f"<p style='color: #475569; font-size: 15px;'>Use the one-time code below to complete your verification:</p>"
            f"<div style='background-color: #f8fafc; border: 1px dashed #cbd5e1; padding: 18px; font-size: 32px; font-weight: 700; letter-spacing: 6px; color: #1e293b; text-align: center; border-radius: 6px; margin: 24px 0;'>{otp}</div>"
            f"<p style='color: #64748b; font-size: 13px; line-height: 1.5;'>This code expires in {settings.OTP_EXPIRY_SECONDS // 60} minutes. For security, never share this code with anyone.<br/>If you did not request this code, please ignore this email.</p>"
            f"</div>"
        )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "from": self.from_address,
            "to": [identifier.strip()],
            "subject": subject,
            "text": text_content,
            "html": html_content,
        }

        try:
            import httpx
            with httpx.Client(timeout=10.0) as client:
                resp = client.post("https://api.resend.com/emails", json=payload, headers=headers)
                if resp.status_code >= 400:
                    err_msg = resp.text
                    logger.error(
                        "resend_otp_delivery_failed",
                        status_code=resp.status_code,
                        error=err_msg,
                        identifier=_mask(identifier),
                    )
                    raise OtpDeliveryError("We couldn't send the verification email. Please try again later.")
            logger.info("resend_otp_delivered", identifier=_mask(identifier))
        except OtpDeliveryError:
            raise
        except Exception as exc:
            logger.error(
                "resend_otp_exception",
                identifier=_mask(identifier),
                error=str(exc),
            )
            raise OtpDeliveryError("We couldn't send the verification email. Please try again later.") from exc

        return OtpDeliveryResult(
            delivered=True,
            channel="email",
            identifier=identifier,
            provider_name=self.provider_name,
            status="delivered",
            otp=None,
        )


class SmsOtpProvider(OtpDeliveryProvider):
    """
    SMS gateway delivery.

    The gateway adapter itself stays out of scope for L1: credentials are
    read from SMS_* env vars and a send request is performed against the
    configured gateway. With no gateway client this provider fails closed
    rather than leaking a code into logs.
    """

    provider_name = "sms"
    delivery_channel = "mobile"

    def _require_config(self) -> None:
        missing = [
            name
            for name, value in (
                ("SMS_ACCOUNT_SID", settings.SMS_ACCOUNT_SID),
                ("SMS_AUTH_TOKEN", settings.SMS_AUTH_TOKEN),
                ("SMS_FROM", settings.SMS_FROM),
            )
            if not value
        ]
        if missing:
            raise OtpDeliveryError(
                f"SMS OTP delivery requires {', '.join(missing)} to be configured."
            )

    def send_otp(
        self,
        *,
        channel: Channel,
        identifier: str,
        otp: str,
        reason: str = "authentication",
    ) -> OtpDeliveryResult:
        if channel != "mobile":
            raise OtpDeliveryError("SmsOtpProvider supports channel='mobile' only.")
        self._require_config()
        # Gateway dispatch is intentionally left to the configured provider
        # package (e.g. twilio-sdk). We fail closed rather than log the code.
        raise OtpDeliveryError(
            "SMS gateway delivery is not wired to a gateway client in this build; "
            "set OTP_PROVIDER=console in development or configure the gateway."
        )


# ---------------------------------------------------------------------------
# Factory + dependency
# ---------------------------------------------------------------------------

def build_otp_delivery_provider(name: str | None = None) -> OtpDeliveryProvider:
    provider_name = (name or settings.OTP_PROVIDER or "console").lower()

    # Automatically use Resend if requested or if RESEND_API_KEY is configured
    if provider_name == "resend" or (bool(settings.RESEND_API_KEY) and provider_name in ("email", "console")):
        if settings.RESEND_API_KEY:
            return ResendOtpProvider()
        if provider_name == "resend":
            raise OtpDeliveryError("OTP_PROVIDER=resend requires RESEND_API_KEY to be configured.")

    if provider_name == "email":
        if settings.SMTP_HOST and settings.SMTP_USER:
            return EmailOtpProvider()
        if settings.ENVIRONMENT == "development":
            logger.warning("otp_provider_fallback_console", wanted="email")
            return ConsoleOtpProvider()
        raise OtpDeliveryError("OTP_PROVIDER=email requires SMTP credentials or RESEND_API_KEY in production.")
    if provider_name == "sms":
        if settings.SMS_ACCOUNT_SID and settings.SMS_AUTH_TOKEN:
            return SmsOtpProvider()
        if settings.ENVIRONMENT == "development":
            logger.warning("otp_provider_fallback_console", wanted="sms")
            return ConsoleOtpProvider()
        raise OtpDeliveryError("OTP_PROVIDER=sms requires SMS credentials in production.")
    if provider_name != "console":
        raise OtpDeliveryError(f"Unknown OTP_PROVIDER: {provider_name!r}")
    return ConsoleOtpProvider()


def get_otp_delivery_provider(request: Request):
    """FastAPI dependency — one provider per app instance, cached on app.state."""
    key = "transformiq_otp_delivery_provider"
    provider = getattr(request.app.state, key, None)
    if provider is None:
        provider = build_otp_delivery_provider()
        setattr(request.app.state, key, provider)
    return provider