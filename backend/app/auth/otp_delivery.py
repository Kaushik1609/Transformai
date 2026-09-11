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
    """Abstract OTP delivery channel."""

    provider_name: str = "abstract"

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
    """Development/test provider. Logs the code only in development."""

    provider_name = "console"

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
        # Test seam: always record the code so offline tests can read it.
        self.recent_codes[(channel, identifier.strip().lower())] = otp
        if settings.ENVIRONMENT == "development":
            logger.info(
                "otp_console_delivery",
                channel=channel,
                identifier=_mask(identifier),
                reason=reason,
                otp=otp,
            )
        else:
            logger.info(
                "otp_console_delivery_redacted",
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
        )

    def last_otp_for(self, channel: Channel, identifier: str) -> str | None:
        return self.recent_codes.get((channel, identifier.strip().lower()))


class EmailOtpProvider(OtpDeliveryProvider):
    """SMTP email delivery. Requires SMTP_HOST and SMTP_USER to be configured."""

    provider_name = "email"

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
        try:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
                server.starttls()
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(message)
        except Exception as exc:
            logger.warning("otp_email_delivery_failed", identifier=_mask(identifier))
            raise OtpDeliveryError(f"Failed to deliver email OTP: {exc}") from exc
        logger.info("otp_email_delivered", identifier=_mask(identifier))
        return OtpDeliveryResult(
            delivered=True,
            channel="email",
            identifier=identifier,
            provider_name=self.provider_name,
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
    if provider_name == "email":
        if settings.SMTP_HOST and settings.SMTP_USER:
            return EmailOtpProvider()
        if settings.ENVIRONMENT == "development":
            logger.warning("otp_provider_fallback_console", wanted="email")
            return ConsoleOtpProvider()
        raise OtpDeliveryError("OTP_PROVIDER=email requires SMTP credentials in production.")
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