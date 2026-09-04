/**
 * TransformIQ — Client identity / session state.
 *
 * Two coexistence modes:
 *
 * 1. Development session (DEV_SESSION_KEY): mirrors the backend
 *    DEV_AUTH_BYPASS mechanism. No tokens are invented and nothing is
 *    transmitted; signing in records the identity the development backend
 *    already trusts.
 *
 * 2. Access token (AUTH_TOKEN_KEY): the Phase 11F L1 token issued by
 *    POST /api/v1/auth/verify. When present it is attached as an
 *    "Authorization: Bearer" header to every API request; the dev-session
 *    flow keeps working for environments where the backend trusts it.
 */
export const DEV_SESSION_KEY = "transformiq.dev_session";
export const AUTH_TOKEN_KEY = "transformiq.access_token";

export interface DevSession {
  email: string;
  name: string;
  role: string;
  signedInAt: string;
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

/** Return the active development session, or null when signed out / SSR. */
export function getDevSession(): DevSession | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(DEV_SESSION_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    return isSession(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

/** Start a development session (backend stays DEV_AUTH_BYPASS-driven). */
export function setDevSession(email: string, name?: string): DevSession {
  const session: DevSession = {
    email: email.trim() || FALLBACK_EMAIL,
    name: (name || "").trim() || FALLBACK_NAME,
    role: FALLBACK_ROLE,
    signedInAt: new Date().toISOString(),
  };
  if (typeof window !== "undefined") {
    window.localStorage.setItem(DEV_SESSION_KEY, JSON.stringify(session));
  }
  return session;
}

/** Clear the development session (existing data is never deleted). */
export function clearDevSession(): void {
  if (typeof window !== "undefined") {
    window.localStorage.removeItem(DEV_SESSION_KEY);
  }
}

// ---------------------------------------------------------------------------
// Access-token helpers (Phase 11F — L1)
// ---------------------------------------------------------------------------

/** Return the stored bearer token, or null on SSR / missing / malformed. */
export function getAuthToken(): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    return window.localStorage.getItem(AUTH_TOKEN_KEY);
  } catch {
    return null;
  }
}

/** Persist a freshly verified access token. */
export function setAuthToken(token: string): void {
  if (typeof window !== "undefined" && token.length > 0) {
    window.localStorage.setItem(AUTH_TOKEN_KEY, token);
  }
}

/** Discard the stored access token (logout). */
export function clearAuthToken(): void {
  if (typeof window !== "undefined") {
    window.localStorage.removeItem(AUTH_TOKEN_KEY);
  }
}

/**
 * Headers merged into every API request. Returns an empty object when no
 * token exists so the development-session flow is untouched.
 */
export function authHeaders(): Record<string, string> {
  const token = getAuthToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}