"""
TransformIQ Backend — Phase 1.5 Stabilization Unit Tests.

Covers:
1. OTP delivery provider abstraction & security (no OTP in responses/results, delivery_channel)
2. Email delivery unavailable / failure handling (never fake verification)
3. Future Twilio / SMS provider interface compatibility
4. File security validation: safe filename validation, path traversal rejection, extension/MIME validation
5. Truthful ClamAV scanner states: unavailable recorded explicitly, never claimed clean
"""

import pytest
from unittest.mock import patch, MagicMock

from app.auth.otp_delivery import (
    OtpDeliveryProvider,
    ConsoleOtpProvider,
    EmailOtpProvider,
    ResendOtpProvider,
    SmsOtpProvider,
    OtpDeliveryResult,
    OtpDeliveryError,
    build_otp_delivery_provider,
)
from app.auth.schemas import OtpDeliveryDetails
from app.ingestion.validation import validate_source, SourceValidationError
from app.services.source_service import _scan_malware, MalwareScanRejected
from app.core.config import Settings
from app.core.audit import clear_security_events


@pytest.fixture(autouse=True)
def reset_audit_events():
    clear_security_events()
    yield
    clear_security_events()


# ===========================================================================
# 1. OTP Delivery & Security Tests
# ===========================================================================

class TestOtpDeliverySecurity:
    def test_console_provider_delivery_channel_and_redaction(self):
        provider = ConsoleOtpProvider()
        assert provider.delivery_channel == "email"
        result = provider.send_otp(channel="email", identifier="user@example.com", otp="123456")
        assert isinstance(result, OtpDeliveryResult)
        assert result.channel == "email"
        assert result.identifier == "user@example.com"
        assert result.status == "delivered"
        # OTP must NOT be returned in result
        assert result.otp is None

    def test_email_provider_delivery_channel(self):
        provider = EmailOtpProvider()
        assert provider.delivery_channel == "email"

    def test_email_provider_smtp_failure_raises_error_without_fake_success(self):
        provider = EmailOtpProvider()
        with patch("app.auth.otp_delivery.settings.SMTP_HOST", "smtp.invalid.domain"), \
             patch("app.auth.otp_delivery.settings.SMTP_USER", "user"), \
             patch("app.auth.otp_delivery.settings.SMTP_PASSWORD", "secret"), \
             patch("app.auth.otp_delivery.settings.SMTP_FROM", "noreply@example.com"):
            with patch("smtplib.SMTP", side_effect=Exception("Connection refused")):
                with pytest.raises(OtpDeliveryError) as exc_info:
                    provider.send_otp(channel="email", identifier="user@example.com", otp="123456")
                assert "couldn't send the verification email" in str(exc_info.value).lower()

    def test_resend_provider_delivery_channel(self):
        provider = ResendOtpProvider(api_key="re_test123")
        assert provider.delivery_channel == "email"
        assert provider.provider_name == "resend"

    def test_resend_provider_missing_key_raises(self):
        provider = ResendOtpProvider(api_key="")
        with pytest.raises(OtpDeliveryError) as exc_info:
            provider.send_otp(channel="email", identifier="user@example.com", otp="123456")
        assert "RESEND_API_KEY" in str(exc_info.value)

    def test_resend_provider_success(self):
        provider = ResendOtpProvider(api_key="re_test123")
        with patch("httpx.Client.post") as mock_post:
            mock_post.return_value.status_code = 200
            result = provider.send_otp(channel="email", identifier="user@example.com", otp="123456")
            assert result.delivered is True
            assert result.status == "delivered"
            assert result.provider_name == "resend"
            assert result.otp is None  # Never exposed! Real inbox proof

    def test_resend_provider_http_error_raises(self):
        provider = ResendOtpProvider(api_key="re_test123")
        with patch("httpx.Client.post") as mock_post:
            mock_post.return_value.status_code = 403
            mock_post.return_value.text = "Forbidden"
            with pytest.raises(OtpDeliveryError) as exc_info:
                provider.send_otp(channel="email", identifier="user@example.com", otp="123456")
            assert "couldn't send the verification email" in str(exc_info.value).lower()

    def test_build_otp_delivery_provider_auto_resend(self):
        with patch("app.auth.otp_delivery.settings.RESEND_API_KEY", "re_auto123"):
            provider = build_otp_delivery_provider("email")
            assert isinstance(provider, ResendOtpProvider)

            provider_explicit = build_otp_delivery_provider("resend")
            assert isinstance(provider_explicit, ResendOtpProvider)

    def test_otp_delivery_details_has_no_dev_otp_field(self):
        details = OtpDeliveryDetails(
            channel="email",
            identifier="test@example.com",
            resend_after_seconds=60,
            delivery_status="delivered",
        )
        assert not hasattr(details, "dev_otp") or details.__dict__.get("dev_otp") is None
        data = details.model_dump()
        assert "dev_otp" not in data
        assert data["delivery_status"] == "delivered"

    def test_future_sms_twilio_provider_conformance(self):
        """Verify that a future SMS / Twilio OTP provider conforms to OtpDeliveryProvider interface."""
        class MockTwilioProvider(OtpDeliveryProvider):
            delivery_channel = "mobile"

            def send_otp(
                self,
                *,
                channel: str,
                identifier: str,
                otp: str,
                reason: str = "authentication",
            ) -> OtpDeliveryResult:
                # Destination is phone number; does not return raw OTP
                return OtpDeliveryResult(
                    delivered=True,
                    channel=channel,
                    identifier=identifier,
                    provider_name="twilio",
                    status="delivered",
                    otp=None,
                )

        provider = MockTwilioProvider()
        assert provider.delivery_channel == "mobile"
        res = provider.send_otp(channel="mobile", identifier="+1234567890", otp="654321")
        assert res.channel == "mobile"
        assert res.identifier == "+1234567890"
        assert res.status == "delivered"
        assert res.otp is None


# ===========================================================================
# 2. File Security Validation Tests
# ===========================================================================

class TestFileSecurityValidation:
    def test_valid_text_file(self):
        content = b"This is a valid test document for ingestion."
        result = validate_source(
            source_type="txt",
            content=content,
            filename="document.txt",
            max_size_bytes=10 * 1024 * 1024,
        )
        assert result.source_type == "txt"
        assert result.filename == "document.txt"

    def test_filename_path_traversal_dot_dot_rejected(self):
        content = b"Some valid content here."
        with pytest.raises(SourceValidationError) as exc:
            validate_source(
                source_type="txt",
                content=content,
                filename="../../etc/passwd.txt",
                max_size_bytes=10 * 1024 * 1024,
            )
        assert "invalid path characters" in str(exc.value).lower()

    def test_filename_path_traversal_forward_slash_rejected(self):
        content = b"Some valid content here."
        with pytest.raises(SourceValidationError) as exc:
            validate_source(
                source_type="txt",
                content=content,
                filename="subfolder/document.txt",
                max_size_bytes=10 * 1024 * 1024,
            )
        assert "invalid path characters" in str(exc.value).lower()

    def test_filename_path_traversal_backslash_rejected(self):
        content = b"Some valid content here."
        with pytest.raises(SourceValidationError) as exc:
            validate_source(
                source_type="txt",
                content=content,
                filename="subfolder\\document.txt",
                max_size_bytes=10 * 1024 * 1024,
            )
        assert "invalid path characters" in str(exc.value).lower()

    def test_filename_null_byte_rejected(self):
        content = b"Some valid content here."
        with pytest.raises(SourceValidationError) as exc:
            validate_source(
                source_type="txt",
                content=content,
                filename="document\x00.txt",
                max_size_bytes=10 * 1024 * 1024,
            )
        assert "invalid control characters" in str(exc.value).lower()

    def test_filename_too_long_rejected(self):
        content = b"Some valid content here."
        long_name = "a" * 256 + ".txt"
        with pytest.raises(SourceValidationError) as exc:
            validate_source(
                source_type="txt",
                content=content,
                filename=long_name,
                max_size_bytes=10 * 1024 * 1024,
            )
        assert "exceeds 255 characters" in str(exc.value).lower()

    def test_disallowed_extension_rejected(self):
        content = b"malicious executable"
        with pytest.raises(SourceValidationError) as exc:
            validate_source(
                source_type="txt",
                content=content,
                filename="malware.exe",
                max_size_bytes=10 * 1024 * 1024,
            )
        assert "extension" in str(exc.value).lower()

    def test_mismatched_mime_magic_rejected(self):
        # Claiming .pdf but content is a docx ZIP header
        content = b"PK\x03\x04 fake docx bytes"
        with pytest.raises(SourceValidationError) as exc:
            validate_source(
                source_type="pdf",
                content=content,
                filename="test.pdf",
                mime_type="application/pdf",
                max_size_bytes=10 * 1024 * 1024,
            )
        assert "does not match its declared type" in str(exc.value).lower()


# ===========================================================================
# 3. Truthful ClamAV Scanner States
# ===========================================================================

class TestTruthfulClamAvStates:
    def test_clamav_unavailable_when_optional_records_explicit_unavailable(self):
        import uuid
        from app.ingestion.malware_scan import FakeMalwareScanner, MalwareScanStatus

        fake_scanner = FakeMalwareScanner(behavior=lambda b: MalwareScanStatus.UNAVAILABLE)
        settings = Settings(
            MALWARE_SCAN_ENABLED=True,
            MALWARE_SCAN_REQUIRED=False,  # Free-tier / development deployment
        )
        with patch("app.services.source_service.settings", settings):
            with patch("app.services.source_service.build_malware_scanner", return_value=fake_scanner):
                result = _scan_malware(content=b"test content", project_id=uuid.uuid4())
                assert result is not None
                assert "malware_scan" in result
                scan_meta = result["malware_scan"]
                assert scan_meta["status"] == "unavailable"
                assert scan_meta["scanner"] == "fake"
                # MUST NOT report "clean" or "passed"
                assert scan_meta["status"] != "clean"

    def test_clamav_unavailable_when_required_fails_closed(self):
        import uuid
        from app.ingestion.malware_scan import FakeMalwareScanner, MalwareScanStatus

        fake_scanner = FakeMalwareScanner(behavior=lambda b: MalwareScanStatus.UNAVAILABLE)
        settings = Settings(
            MALWARE_SCAN_ENABLED=True,
            MALWARE_SCAN_REQUIRED=True,  # Strict production requirement
        )
        with patch("app.services.source_service.settings", settings):
            with patch("app.services.source_service.build_malware_scanner", return_value=fake_scanner):
                with pytest.raises(MalwareScanRejected):
                    _scan_malware(content=b"test content", project_id=uuid.uuid4())

    def test_clamav_infected_when_required_fails_closed(self):
        import uuid
        from app.ingestion.malware_scan import FakeMalwareScanner

        fake_scanner = FakeMalwareScanner()
        settings = Settings(
            MALWARE_SCAN_ENABLED=True,
            MALWARE_SCAN_REQUIRED=True,
        )
        with patch("app.services.source_service.settings", settings):
            with patch("app.services.source_service.build_malware_scanner", return_value=fake_scanner):
                with pytest.raises(MalwareScanRejected):
                    _scan_malware(
                        content=FakeMalwareScanner.EICAR.encode("utf-8"),
                        project_id=uuid.uuid4(),
                    )

    def test_clamav_infected_when_optional_records_infected_never_clean(self):
        import uuid
        from app.ingestion.malware_scan import FakeMalwareScanner

        fake_scanner = FakeMalwareScanner()
        settings = Settings(
            MALWARE_SCAN_ENABLED=True,
            MALWARE_SCAN_REQUIRED=False,
        )
        with patch("app.services.source_service.settings", settings):
            with patch("app.services.source_service.build_malware_scanner", return_value=fake_scanner):
                result = _scan_malware(
                    content=FakeMalwareScanner.EICAR.encode("utf-8"),
                    project_id=uuid.uuid4(),
                )
                assert result is not None
                assert result["malware_scan"]["status"] == "infected"
                assert result["malware_scan"]["status"] != "clean"
