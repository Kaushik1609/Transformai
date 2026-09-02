/**
 * TransformIQ — Development identity / session state.
 *
 * The backend authenticates via a stable development identity
 * (DEV_AUTH_BYPASS=true). This module mirrors that mechanism on the client
 * with a lightweight local session: no tokens are invented, no credentials are
 * stored, and nothing is transmitted. Signing in simply records the identity
 * that the development backend already trusts; logging out clears it.
 */
export const DEV_SESSION_KEY = "transformiq.dev_session";

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