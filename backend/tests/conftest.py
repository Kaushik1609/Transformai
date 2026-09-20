"""
TransformIQ / KaryaSetu AI — Test Suite Configuration (conftest.py)

Provides deterministic, offline-capable environment defaults for all backend test suites.
Enables tests to run in isolated offline/development mode without requiring live external API keys.
Never injects production secrets.
"""
import os
import pytest
from app.core.config import settings

# Configure safe test environment defaults
@pytest.fixture(autouse=True, scope="session")
def configure_offline_test_environment():
    """Ensure tests have safe, mock provider credentials and offline routing targets."""
    # Set default test credentials on cached settings if empty
    if not getattr(settings, "LLM_API_KEY", None):
        object.__setattr__(settings, "LLM_API_KEY", "test-mock-api-key-offline")
    if not getattr(settings, "EMBEDDING_API_KEY", None):
        object.__setattr__(settings, "EMBEDDING_API_KEY", "test-mock-embedding-key-offline")
    if not getattr(settings, "AUTH_SECRET_KEY", None) or settings.AUTH_SECRET_KEY == "dev-secret-replace-before-production":
        object.__setattr__(settings, "AUTH_SECRET_KEY", "test-secret-at-least-32-characters-long-12345")
    os.environ["EMBEDDING_PROVIDER"] = "fake"
    object.__setattr__(settings, "EMBEDDING_PROVIDER", "fake")
    object.__setattr__(settings, "MALWARE_SCAN_REQUIRED", False)
    yield
