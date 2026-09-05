/**
 * TransformIQ — Client identity / session state.
 *
 * Two coexistence modes:
 *
 * 1. Development session (DEV_SESSION_KEY): mirrors the backend
 *    DEV_AUTH_BYPASS mechanism. No tokens are invented and nothing is
 *    transmitted; signing in records the identity the development backend
 *    already trusts. Access through this path is ONLY permitted when the
 *    frontend build explicitly enables it via NEXT_PUBLIC_DEV_AUTH_BYPASS=true
 *    — it is never the default, silent behavior.
 *
 * 2. Access token (AUTH_STORE_KEY): the Phase 11F L1 JWT issued by
 *    POST /api/v1/auth/verify. The token and its expiry are stored together
 *    in a single object so the auth gate can detect (and clear) expired
 *    credentials. It is attached as an "Authorization: Bearer" header to
 *    every API request via authHeaders().
 */
export const DEV_SESSION_KEY = "transformiq.dev_session";
export const AUTH_STORE_KEY = "transformiq.auth";
export const LEGACY_AUTH_TOKEN_KEY = "transformiq.access_token";

export interface DevSession {
  email: string;
  name: string;
  role: string;
  signedInAt: string;
}

export interface StoredAuth {
  token: string;
  /** Epoch milliseconds at which the token stops being valid. */
  expiresAt: number;
}

const FALLBACK_NAME = "Development User";
const FALLBACK_EMAIL = "dev@transformiq.local";
const FALLBACK_ROLE = "operator";

function isSession(value: unknown): value is DevSession {
  if (typeof value !== "object" || value === null) return false;
  const session = value as Record<string, unknown>;
  return (
    typeof session.email === "string" &&
    typeof session.name === "string" &&
    typeof session.role === "string" &&
    typeof session.signedInAt === "string"
  );
}

/** Guarded access to the browser storage used by the auth helpers. */
function storage(): Storage | null {
  try {
    return typeof window !== "undefined" ? window.localStorage : null;
  } catch {
    return null;
  }
}

function readStoredAuth(): StoredAuth | null {
  const store = storage();
  if (!store) return null;
  try {
    const raw = store.getItem(AUTH_STORE_KEY);
    if (!raw) return null;
    const parsed: Partial<StoredAuth> = JSON.parse(raw);
    if (
      typeof parsed.token === "string" &&
      parsed.token.length > 0 &&
      typeof parsed.expiresAt === "number" &&
      Number.isFinite(parsed.expiresAt)
    ) {
      return { token: parsed.token, expiresAt: parsed.expiresAt };
    }
    return null;
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Development-session helpers
// ---------------------------------------------------------------------------

/** Return the active development session, or null when signed out / SSR. */
export function getDevSession(): DevSession | null {
  const store = storage();
  if (!store) return null;
  try {
    const raw = store.getItem(DEV_SESSION_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    return isSession(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

/** Start a development session (only reachable when dev bypass is enabled). */
export function setDevSession(email: string, name?: string): DevSession {
  const session: DevSession = {
    email: email.trim() || FALLBACK_EMAIL,
    name: (name || "").trim() || FALLBACK_NAME,
    role: FALLBACK_ROLE,
    signedInAt: new Date().toISOString(),
  };
  const store = storage();
  if (store) {
    try {
      store.setItem(DEV_SESSION_KEY, JSON.stringify(session));
    } catch {
      // storage unavailable — ignore
    }
  }
  return session;
}

/**
 * Clear the development session. Also discards any stored access token so a
 * logout from the profile menu never leaves live credentials behind.
 */
export function clearDevSession(): void {
  clearAuthToken();
  const store = storage();
  if (store) {
    try {
      store.removeItem(DEV_SESSION_KEY);
    } catch {
      // storage unavailable — ignore
    }
  }
}

// ---------------------------------------------------------------------------
// Access-token helpers (Phase 11F — L1)
// ---------------------------------------------------------------------------

/**
 * True only when the frontend build was explicitly configured for the
 * development identity bypass (NEXT_PUBLIC_DEV_AUTH_BYPASS=true). Read at
 * call-time so tests and build-time flags behave consistently.
 */
export function isDevAuthBypassEnabled(): boolean {
  return process.env.NEXT_PUBLIC_DEV_AUTH_BYPASS === "true";
}

/** Persist a verified access token together with its expiry (epoch ms). */
export function setAuthToken(token: string, expiresAt: number): void {
  const store = storage();
  if (!store || !token || typeof expiresAt !== "number" || !Number.isFinite(expiresAt)) {
    return;
  }
  try {
    const stored: StoredAuth = { token, expiresAt };
    store.setItem(AUTH_STORE_KEY, JSON.stringify(stored));
  } catch {
    // storage unavailable — ignore
  }
}

/** Return the stored bearer token, or null on SSR / missing / malformed. */
export function getAuthToken(): string | null {
  const stored = readStoredAuth();
  return stored ? stored.token : null;
}

/** Return the stored token expiry (epoch ms), or null when absent. */
export function getAuthExpiry(): number | null {
  const stored = readStoredAuth();
  return stored ? stored.expiresAt : null;
}

/** True when a token exists AND its expiry has not yet passed. */
export function isTokenValid(): boolean {
  const stored = readStoredAuth();
  return stored !== null && stored.expiresAt > Date.now();
}

/** Remove all auth-related storage keys (current store + legacy leftovers). */
export function clearAuthToken(): void {
  const store = storage();
  if (!store) return;
  try {
    store.removeItem(AUTH_STORE_KEY);
    store.removeItem(LEGACY_AUTH_TOKEN_KEY);
  } catch {
    // storage unavailable — ignore
  }
}

/**
 * Headers merged into every API request. Returns an empty object when no
 * valid token exists so the development-session flow is untouched.
 */
export function authHeaders(): Record<string, string> {
  const token = getAuthToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}