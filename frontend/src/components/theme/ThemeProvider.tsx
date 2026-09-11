/**
 * TransformIQ — Theme provider.
 *
 * Persists the appearance choice (Light / Dark / System) under
 * `transformiq:theme` and syncs the `.dark` class on <html> so every
 * `darkMode: ["class"]` token resolves correctly.
 *
 * The FOUC-prevention inline script in the root layout applies the stored
 * choice before first paint; this provider keeps it in sync for the rest of
 * the session (including system theme changes while "System" is selected).
 */
"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

export type Theme = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

export const THEME_KEY = "transformiq:theme";

type ThemeContextValue = {
  theme: Theme;
  resolved: ResolvedTheme;
  setTheme: (theme: Theme) => void;
};

const ThemeContext = createContext<ThemeContextValue>({
  theme: "system",
  resolved: "dark",
  setTheme: () => {},
});

function isTheme(value: unknown): value is Theme {
  return value === "light" || value === "dark" || value === "system";
}

/**
 * Read the persisted theme once, at first render. Returns "system" on the
 * server (no window) or when storage is unavailable/invalid, so mount never
 * rewrites an existing stored value.
 */
function readStoredTheme(): Theme {
  if (typeof window === "undefined") return "system";
  try {
    const stored = window.localStorage.getItem(THEME_KEY);
    return isTheme(stored) ? stored : "system";
  } catch {
    return "system";
  }
}

function resolve(theme: Theme): ResolvedTheme {
  if (theme === "system") {
    if (typeof window === "undefined") return "dark";
    return window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  }
  return theme;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>("system");
  const [resolved, setResolved] = useState<ResolvedTheme>("dark");

  function applyTheme(next: ResolvedTheme) {
    document.documentElement.classList.toggle("dark", next === "dark");
  }

  // Adopt the persisted choice once on mount. This is the only storage read;
  // nothing is written to storage on mount, so an existing stored theme is
  // never transiently overwritten. The class is applied synchronously here
  // (the inline bootstrap script already handled pre-paint) so a stored
  // light theme never flashes dark.
  useEffect(() => {
    const stored = readStoredTheme();
    const initial = resolve(stored);
    applyTheme(initial);
    setTheme(stored);
    setResolved(initial);
  }, []);

  // Keep "System" live when the OS preference changes.
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = () => {
      if (theme !== "system") return;
      const next = resolve("system");
      applyTheme(next);
      setResolved(next);
    };
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, [theme]);

  const setAndResolve = (next: Theme) => {
    const value = resolve(next);
    applyTheme(value);
    setTheme(next);
    setResolved(value);
    try {
      window.localStorage.setItem(THEME_KEY, next);
    } catch {
      // storage unavailable — ignore
    }
  };

  return (
    <ThemeContext.Provider
      value={{ theme, resolved, setTheme: setAndResolve }}
    >
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  return useContext(ThemeContext);
}