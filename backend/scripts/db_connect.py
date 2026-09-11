"""
TransformIQ — Supabase / Postgres connectivity check.

Reads the database configuration the same way the API does:

1. Individual ``user`` / ``password`` / ``host`` / ``port`` / ``dbname``
   environment variables (the standalone snippet form), OR
2. The project's ``DATABASE_URL`` / ``DATABASE_SYNC_URL`` connection strings
   used by the backend (``backend/app/core/config.py``). When both are present
   each is tested so a broken sync/async pairing is surfaced.

Credentials are never hard-coded here; the password is never printed.
"""
import os
from pathlib import Path
from urllib.parse import quote_plus, unquote, urlsplit

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CWD = Path.cwd()


def _load_env():  # type: ignore[no-untyped-def]
    """Load the repo root .env (used by the backend) or the CWD .env."""
    candidates = [
        _CWD / ".env",
        _REPO_ROOT / ".env",
    ]
    for candidate in candidates:
        if candidate.exists():
            load_dotenv(candidate)
            return candidate
    load_dotenv()
    return None


def _components_from_url(url: str):  # type: ignore[no-untyped-def]
    """Parse user/host/port/dbname out of a SQLAlchemy URL."""
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    port = parsed.port or 5432
    user = parsed.username or ""
    dbname = (parsed.path.lstrip("/").split("/") or [""])[0]
    return user, host, int(port), dbname


def _ensure_sslmode(url: str) -> str:  # type: ignore[no-untyped-def]
    if "sslmode" not in url:
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}sslmode=require"
    return url


def _candidate_urls():  # type: ignore[no-untyped-def]
    """Build the URL(s) to test from the configured environment."""
    user = os.getenv("user")
    password = os.getenv("password")
    host = os.getenv("host")
    port = os.getenv("port") or "5432"
    dbname = os.getenv("dbname")

    if user and host and dbname:
        password = password or ""
        url = (
            f"postgresql+psycopg2://{user}:{quote_plus(password)}"
            f"@{host}:{port}/{dbname}?sslmode=require"
        )
        return [("standalone snippet", url)]

    urls: dict[str, str] = {}
    if os.getenv("DATABASE_URL"):
        urls["DATABASE_URL  (async engine)"] = _ensure_sslmode(os.environ["DATABASE_URL"])
    if os.getenv("DATABASE_SYNC_URL"):
        urls["DATABASE_SYNC_URL (migrations/scripts)"] = _ensure_sslmode(
            os.environ["DATABASE_SYNC_URL"]
        )
    if not urls:
        raise SystemExit(
            "No database configuration found. Add DATABASE_URL / DATABASE_SYNC_URL "
            "(or user/password/host/port/dbname) to .env."
        )
    return list(urls.items())


def _test(url: str) -> tuple[bool, str]:  # type: ignore[no-untyped-def]
    """Connect once and report success/failure without leaking the password."""
    from urllib.parse import unquote as _u

    user, host, port, dbname = _components_from_url(url)
    del _u  # (parsing only via urlsplit; password never printed)
    from sqlalchemy.pool import NullPool

    engine = create_engine(url, poolclass=NullPool, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            value = connection.execute(text("SELECT 1")).scalar()
            return True, f"{user}@{host}:{port}/{dbname} -> {value}"
    except Exception as exc:  # noqa: BLE001 - connectivity diagnostics by design
        return False, f"{user}@{host}:{port}/{dbname} -> {str(exc)[:220]}"
    finally:
        engine.dispose()


def main():  # type: ignore[no-untyped-def]
    env_file = _load_env()
    print("Loaded env :", env_file.name if env_file else "(none)")

    all_ok = True
    for label, url in _candidate_urls():
        ok, detail = _test(url)
        status = "OK    " if ok else "FAILED"
        if not ok:
            all_ok = False
        print(f"[{status}] {label}: {detail}")

    if not all_ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()