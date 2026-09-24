"""
TransformIQ / KaryaSetu AI — Digital Signatures & Trusted Artifact Signing (Phase 2H)

Responsible for:
1. DigitalSigner abstraction (ABC) supporting asymmetric digital signatures, test mock signers, and symmetric MACs.
2. Ed25519Signer: Production digital signature provider (asymmetric, non-repudiation).
3. FakeDigitalSigner: Deterministic test/offline mock signer.
4. HmacSha256Signer: Explicit symmetric Message Authentication Code (MAC) provider (not an asymmetric digital signature).
5. Deterministic signing payload builder derived strictly from Phase 2G cryptographic integrity envelopes.
6. Persistent DigitalSignatureRecord data model for output_metadata["digital_signature"].
7. Read-only verification and tamper detection.

Guarantees:
- Digital signatures establish authenticity and integrity verification; they are NEVER authorization.
- Zero private keys in source code, metadata, database, audit events, or API responses.
- Symmetric MAC (HMAC-SHA256) is explicitly treated as a MAC, never conflated with asymmetric digital signatures.
- Verification is strictly read-only and never re-signs or mutates stored records.
- Legacy or unsigned outputs honestly evaluate to UNAVAILABLE (no historical signature fabrication).
"""
from __future__ import annotations

import abc
import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.policy.integrity import canonical_json_bytes, canonical_json_hash, sha256_bytes


# ---------------------------------------------------------------------------
# Domain Enums & Constants
# ---------------------------------------------------------------------------

class SignatureStatus(str, Enum):
    """Authoritative digital signature verification status."""

    VALID = "VALID"
    INVALID = "INVALID"
    UNAVAILABLE = "UNAVAILABLE"


class ProviderType(str, Enum):
    """Type classification of signing provider."""

    ASYMMETRIC_SIGNATURE = "asymmetric_signature"
    SYMMETRIC_MAC = "symmetric_mac"
    TEST_MOCK = "test_mock"


DEFAULT_KEY_ID = "karyasetu-dev-key-1"


# ---------------------------------------------------------------------------
# DigitalSigner Abstract Base Class
# ---------------------------------------------------------------------------

class DigitalSigner(abc.ABC):
    """Abstract interface for artifact signing and verification providers."""

    algorithm: str
    key_id: str
    provider_name: str
    provider_type: ProviderType
    is_asymmetric: bool

    @abc.abstractmethod
    def sign(self, payload_bytes: bytes) -> str:
        """Sign or authenticate payload bytes, returning a safe encoded signature string."""
        ...

    @abc.abstractmethod
    def verify(self, payload_bytes: bytes, signature_str: str, key_id: str | None = None) -> bool:
        """Verify signature string against payload bytes."""
        ...

    @abc.abstractmethod
    def get_public_key_info(self) -> dict[str, Any]:
        """Return safe, non-secret public verification metadata (key ID, algorithm, public key)."""
        ...

    def get_public_metadata(self) -> dict[str, Any]:
        """Return safe public metadata including provider capabilities."""
        info = dict(self.get_public_key_info())
        info.setdefault("provider_name", self.provider_name)
        info.setdefault("provider_type", self.provider_type.value)
        info.setdefault("is_asymmetric", self.is_asymmetric)
        info.setdefault("supports_non_repudiation", self.is_asymmetric)
        return info


# ---------------------------------------------------------------------------
# 1. FakeDigitalSigner (Deterministic Test / Offline Mock Provider)
# ---------------------------------------------------------------------------

class FakeDigitalSigner(DigitalSigner):
    """Deterministic mock signing provider for offline/local execution and unit testing."""

    algorithm = "fake-sha256"
    provider_name = "FakeDigitalSigner"
    provider_type = ProviderType.TEST_MOCK
    is_asymmetric = False

    def __init__(self, key_id: str = DEFAULT_KEY_ID, secret: str = "mock-signer-internal-test-key") -> None:
        self.key_id = key_id
        self._secret = secret

    def sign(self, payload_bytes: bytes) -> str:
        # Deterministic 64-char lowercase hex digest
        return hashlib.sha256(self._secret.encode("utf-8") + b"::" + payload_bytes).hexdigest().lower()

    def verify(self, payload_bytes: bytes, signature_str: str, key_id: str | None = None) -> bool:
        if key_id and key_id != self.key_id:
            return False
        if not signature_str:
            return False
        expected = self.sign(payload_bytes)
        return signature_str == expected

    def get_public_key_info(self) -> dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "key_id": self.key_id,
            "provider_type": self.provider_type.value,
            "is_asymmetric": self.is_asymmetric,
            "public_identity": f"mock://{self.key_id}",
        }


# ---------------------------------------------------------------------------
# 2. Ed25519Signer (Production Asymmetric Digital Signature Provider)
# ---------------------------------------------------------------------------

class Ed25519Signer(DigitalSigner):
    """Authoritative production asymmetric digital signature provider using Ed25519.

    Provides true cryptographic non-repudiation and asymmetric signature guarantees.
    Private key is held securely in memory or HSM and never exposed; public key is shared.
    """

    algorithm = "ed25519"
    provider_name = "Ed25519Signer"
    provider_type = ProviderType.ASYMMETRIC_SIGNATURE
    is_asymmetric = True

    def __init__(
        self,
        private_key_bytes: bytes | None = None,
        key_id: str = "karyasetu-ed25519-primary",
    ) -> None:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
            Ed25519PublicKey,
        )
        from cryptography.hazmat.primitives import serialization

        self.key_id = key_id
        if private_key_bytes is not None:
            if len(private_key_bytes) == 32:
                self._private_key = Ed25519PrivateKey.from_private_bytes(private_key_bytes)
            else:
                raise ValueError("Ed25519 raw private key must be exactly 32 bytes.")
        else:
            self._private_key = Ed25519PrivateKey.generate()

        self._public_key: Ed25519PublicKey = self._private_key.public_key()
        raw_pub = self._public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        self.public_key_hex = raw_pub.hex().lower()

    def sign(self, payload_bytes: bytes) -> str:
        """Produce 64-byte Ed25519 raw signature formatted as lowercase hex (128 chars)."""
        raw_sig = self._private_key.sign(payload_bytes)
        return raw_sig.hex().lower()

    def verify(self, payload_bytes: bytes, signature_str: str, key_id: str | None = None) -> bool:
        """Verify Ed25519 hex signature against payload bytes."""
        from cryptography.exceptions import InvalidSignature

        if key_id and key_id != self.key_id:
            return False
        try:
            raw_sig = bytes.fromhex(signature_str)
            self._public_key.verify(raw_sig, payload_bytes)
            return True
        except (InvalidSignature, ValueError, TypeError):
            return False

    def get_public_key_info(self) -> dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "key_id": self.key_id,
            "provider_type": self.provider_type.value,
            "is_asymmetric": self.is_asymmetric,
            "public_key_hex": self.public_key_hex,
        }


# ---------------------------------------------------------------------------
# 3. HmacSha256Signer (Symmetric Message Authentication Code Provider)
# ---------------------------------------------------------------------------

class HmacSha256Signer(DigitalSigner):
    """Explicit symmetric Message Authentication Code (MAC) provider.

    IMPORTANT ARCHITECTURAL NOTE:
    HMAC-SHA256 is a symmetric MAC, NOT an asymmetric digital signature.
    It does not provide asymmetric non-repudiation because the same key is used
    for generation and verification. It is provided strictly as an authenticated
    MAC option when explicitly configured.
    """

    algorithm = "hmac-sha256"
    provider_name = "HmacSha256Signer"
    provider_type = ProviderType.SYMMETRIC_MAC
    is_asymmetric = False

    def __init__(
        self,
        secret: bytes | str | None = None,
        key: bytes | str | None = None,
        key_id: str = "karyasetu-hmac-mac-1",
    ) -> None:
        raw_sec = key if key is not None else secret
        if raw_sec is None:
            raw_sec = b"default-hmac-dev-secret-string"
        self.key_id = key_id
        self._secret = raw_sec.encode("utf-8") if isinstance(raw_sec, str) else raw_sec

    def sign(self, payload_bytes: bytes) -> str:
        import hmac

        return hmac.new(self._secret, payload_bytes, hashlib.sha256).hexdigest().lower()

    def verify(self, payload_bytes: bytes, signature_str: str, key_id: str | None = None) -> bool:
        import hmac

        if key_id and key_id != self.key_id:
            return False
        expected = self.sign(payload_bytes)
        return hmac.compare_digest(signature_str, expected)

    def get_public_key_info(self) -> dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "key_id": self.key_id,
            "provider_type": self.provider_type.value,
            "is_asymmetric": self.is_asymmetric,
            "mac_identifier": f"hmac://{self.key_id}",
        }


# ---------------------------------------------------------------------------
# Provider Factory & Test Overrides
# ---------------------------------------------------------------------------

_ACTIVE_SIGNER: DigitalSigner | None = None


def set_digital_signer_provider(signer: DigitalSigner | None) -> None:
    """Explicitly set or reset the active signer provider (used for test injection)."""
    global _ACTIVE_SIGNER
    _ACTIVE_SIGNER = signer


def get_digital_signer(
    provider_override: str | None = None,
    key_id: str | None = None,
) -> DigitalSigner:
    """Resolve the active digital signer provider based on configuration.

    Production preference:
    - If configured for 'ed25519' -> Ed25519Signer
    - If configured for 'hmac' / 'hmac-sha256' -> HmacSha256Signer (explicit symmetric MAC)
    - Default (dev / test offline) -> FakeDigitalSigner
    """
    global _ACTIVE_SIGNER

    if _ACTIVE_SIGNER is not None and not provider_override:
        return _ACTIVE_SIGNER

    import os
    provider = (
        provider_override
        or os.environ.get("DIGITAL_SIGNATURE_PROVIDER", "fake")
    ).lower()

    if provider in ("ed25519", "asymmetric"):
        raw_key_hex = os.environ.get("ED25519_PRIVATE_KEY_HEX")
        priv_bytes = bytes.fromhex(raw_key_hex) if raw_key_hex else None
        return Ed25519Signer(
            private_key_bytes=priv_bytes,
            key_id=key_id or os.environ.get("ED25519_KEY_ID", "karyasetu-ed25519-primary"),
        )
    elif provider in ("hmac", "hmac-sha256"):
        secret = os.environ.get("HMAC_SIGNING_SECRET", "default-hmac-dev-secret-string")
        return HmacSha256Signer(
            secret=secret,
            key_id=key_id or "karyasetu-hmac-mac-1",
        )
    else:
        # Default mock test signer
        return FakeDigitalSigner(key_id=key_id or DEFAULT_KEY_ID)


# ---------------------------------------------------------------------------
# Deterministic Signing Payload Builder
# ---------------------------------------------------------------------------

def build_signing_payload(
    output_or_envelope: Any,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Construct deterministic canonical signing payload derived from Phase 2G integrity state.

    Binds immutable governance and cryptographic facts:
    - integrity_algorithm
    - artifact_hash
    - companion_hashes
    - provenance_id
    - provenance_hash
    - approval_id
    - output_type
    - classification
    - policy_id

    Strictly excludes:
    - volatile timestamps (created_at, signed_at, recorded_at)
    - private keys
    - signature itself
    - credentials or secrets
    """
    if metadata is not None:
        integ = output_or_envelope if isinstance(output_or_envelope, dict) else {}
        meta = metadata
        output = None
    else:
        output = output_or_envelope
        meta = getattr(output, "output_metadata", None)
        if not isinstance(meta, dict):
            meta = output if isinstance(output, dict) else {}
        integ = meta.get("cryptographic_integrity") or {}

    prov = meta.get("provenance") or {}

    companion_hashes = integ.get("companion_hashes", {})
    sorted_companions = {k: companion_hashes[k] for k in sorted(companion_hashes.keys())}

    classification = meta.get("classification")
    if not classification and "source" in prov and isinstance(prov["source"], dict):
        classification = prov["source"].get("classification")
    if not classification:
        classification = "INTERNAL"

    policy_id = meta.get("policy_id")
    if not policy_id and "policy_routing" in prov and isinstance(prov["policy_routing"], dict):
        policy_id = prov["policy_routing"].get("policy_id")
    elif not policy_id and "dissemination" in prov and isinstance(prov["dissemination"], dict):
        policy_id = prov["dissemination"].get("policy_id")
    if not policy_id:
        policy_id = "karyasetu-policy-v1"

    prov_id = integ.get("provenance_id") or prov.get("id") or prov.get("provenance_id")
    output_type = (
        meta.get("output_type")
        or (getattr(output, "output_type", None) if output else None)
        or prov.get("generator", {}).get("output_type")
    )

    return {
        "integrity_algorithm": integ.get("algorithm", "sha256"),
        "artifact_hash": integ.get("artifact_hash"),
        "companion_hashes": sorted_companions,
        "provenance_id": prov_id,
        "provenance_hash": integ.get("provenance_hash"),
        "approval_id": integ.get("approval_id"),
        "output_type": output_type,
        "classification": classification,
        "policy_id": policy_id,
    }



def compute_signing_payload_bytes(payload: dict[str, Any]) -> bytes:
    """Deterministic UTF-8 canonical JSON serialization of signing payload."""
    return canonical_json_bytes(payload)


def compute_signing_payload_hash(payload: dict[str, Any]) -> str:
    """Lowercase SHA-256 hex digest of the canonical signing payload."""
    return canonical_json_hash(payload)


# ---------------------------------------------------------------------------
# Digital Signature Record Pydantic Model
# ---------------------------------------------------------------------------

class DigitalSignatureRecord(BaseModel):
    """Persistent digital signature record stored under output.output_metadata['digital_signature']."""

    model_config = ConfigDict(extra="forbid")

    algorithm: str = Field(..., description="Signing algorithm ('ed25519', 'fake-sig-v1', 'hmac-sha256').")
    key_id: str = Field(..., description="Public key or key reference identifier.")
    signature: str = Field(..., description="Cryptographic signature string.")
    signed_payload_hash: str = Field(..., description="SHA-256 digest of the canonical signing payload.")
    signed_integrity_hash: str = Field(..., description="Authoritative primary artifact hash signed.")
    signed_provenance_hash: str = Field(..., description="Authoritative provenance hash signed.")
    status: str = Field(default=SignatureStatus.VALID.value, description="Signature status ('VALID').")
    signed_at: str = Field(..., description="ISO 8601 UTC timestamp when signature was generated.")
    provider: str = Field(..., description="Signer provider name or category.")
