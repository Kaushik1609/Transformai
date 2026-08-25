# tests/

Top-level test directory for integration tests and shared test utilities.

Unit tests and API tests live alongside the application code they test:

```
backend/tests/     — FastAPI unit and integration tests (pytest)
frontend/src/__tests__/  — React/TypeScript component and utility tests (Jest)
```

This directory is reserved for:
- End-to-end integration tests (added in Phase 11)
- Cross-service test fixtures and helpers
- AI evaluation datasets (added in Phase 11)
