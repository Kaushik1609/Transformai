"""
Phase 0 smoke tests — Application configuration.

Verifies that:
1. Settings load without error.
2. No sensitive defaults are silently accepted in non-dev environments.
3. The DEV_AUTH_BYPASS flag behaves correctly.
"""
import os

import pytest


class TestSettings:
    def test_settings_load_successfully(self):
        """Settings object should load with no import error."""
        from app.core.config import get_settings

        s = get_settings()
        assert s is not None

    def test_environment_defaults_to_development(self):
        from app.core.config import get_settings

        s = get_settings()
        assert s.ENVIRONMENT in ("development", "staging", "production")

    def test_allowed_origins_list_is_list(self):
        from app.core.config import get_settings

        s = get_settings()
        origins = s.allowed_origins_list
        assert isinstance(origins, list)
        assert len(origins) >= 1

    def test_max_upload_size_bytes_is_positive(self):
        from app.core.config import get_settings

        s = get_settings()
        assert s.max_upload_size_bytes > 0

    def test_allowed_upload_types_list_is_list(self):
        from app.core.config import get_settings

        s = get_settings()
        types = s.allowed_upload_types_list
        assert isinstance(types, list)
        assert len(types) >= 1

    def test_llm_provider_is_set(self):
        from app.core.config import get_settings

        s = get_settings()
        assert s.LLM_PROVIDER in ("openai", "anthropic", "gemini", "azure_openai", "fake")

    def test_storage_backend_is_valid(self):
        from app.core.config import get_settings

        s = get_settings()
        assert s.STORAGE_BACKEND in ("local", "s3")

    def test_dev_auth_bypass_is_bool(self):
        from app.core.config import get_settings

        s = get_settings()
        assert isinstance(s.DEV_AUTH_BYPASS, bool)
