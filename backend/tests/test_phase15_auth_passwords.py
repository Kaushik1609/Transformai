"""
TransformIQ Backend — Phase 15 password hardening unit tests.

Covers the password hashing primitive (`app.core.password`) and the password
field policy enforced by `app.auth.schemas`.  App/db-backed flows (login
denial-reason mapping, registration hash storage) live in
`test_phase11f_auth.py` under the "Phase 15" sections, reusing its `auth_ctx`
app fixture.
"""

import pytest

from app.core.password import hash_password, verify_password


# ===========================================================================
# 1. Hashing primitive
# ===========================================================================

class TestPasswordHasher:
    def test_hash_format_is_self_describing(self):
        stored = hash_password("Correct-Horse-Battery-1!")
        algo, iterations, salt_b64, digest_b64 = stored.split("$")
        assert algo == "pbkdf2_sha256"
        assert int(iterations) == 310_000
        assert salt_b64
        assert digest_b64
        assert "Correct-Horse-Battery-1!" not in stored

    def test_verify_correct_and_wrong(self):
        stored = hash_password("Correct-Horse-Battery-1!")
        assert verify_password("Correct-Horse-Battery-1!", stored)
        assert not verify_password("Wrong-Horse-Battery-2!", stored)
        assert not verify_password("", stored)

    def test_same_password_different_salts(self):
        a = hash_password("same-pw-123!")
        b = hash_password("same-pw-123!")
        assert a != b
        assert verify_password("same-pw-123!", a)
        assert verify_password("same-pw-123!", b)

    def test_malformed_stored_hash_fails_closed(self):
        assert not verify_password("anything", "")
        assert not verify_password("anything", "garbage")
        assert not verify_password("anything", "pbkdf2_sha256$x$y")
        assert not verify_password("anything", "bcrypt$10$abc")
        assert not verify_password("anything", "pbkdf2_sha256$0$c2FsdA==$ZGlnZXN0")
        assert not verify_password("anything", "pbkdf2_sha256$-5$c2FsdA==$ZGlnZXN0")
        assert not verify_password("anything", "pbkdf2_sha256$10$!!!$!!!")

    def test_verify_runs_off_thread(self):
        # The service calls this via asyncio.to_thread; the functions must be
        # plain-sync so they can be offloaded without an event loop.
        import inspect

        assert not inspect.iscoroutinefunction(hash_password)
        assert not inspect.iscoroutinefunction(verify_password)

    def test_legacy_iteration_count_still_verifies(self):
        # Lower iteration counts (from a future rollback) must still verify,
        # which is why the storage format carries the iteration count.
        import base64
        import hashlib
        import hmac
        import secrets

        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", b"legacy-pw!", salt, 100_000, dklen=32)
        stored = (
            f"pbkdf2_sha256$100000$"
            f"{base64.b64encode(salt).decode()}$"
            f"{base64.b64encode(digest).decode()}"
        )
        assert verify_password("legacy-pw!", stored)


# ===========================================================================
# 2. Password field policy (schema level)
# ===========================================================================

class TestPasswordPolicy:
    def _register_request(self, password: str):
        from app.auth.schemas import RegisterRequest

        return RegisterRequest(name="P", email="p@x.com", password=password)

    def test_min_length_8(self):
        with pytest.raises(ValueError):
            self._register_request("1234567")

    def test_max_length_128(self):
        with pytest.raises(ValueError):
            self._register_request("x" * 129)

    def test_no_leading_or_trailing_whitespace(self):
        with pytest.raises(ValueError):
            self._register_request(" padded-pw-1!")
        with pytest.raises(ValueError):
            self._register_request("padded-pw-1! ")

    def test_valid_password_accepted(self):
        req = self._register_request("Register-pw-1!")
        assert req.password == "Register-pw-1!"

    def test_reset_password_confirm_shape(self):
        from app.auth.schemas import ResetPasswordRequest

        req = ResetPasswordRequest(
            email="p@x.com",
            otp="123456",
            new_password="New-pass-99!",
        )
        assert req.email == "p@x.com"
        assert req.new_password == "New-pass-99!"