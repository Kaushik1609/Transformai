/**
 * TransformIQ — Settings page.
 *
 * Navigation: Account, Preferences, AI / Generation, Notifications, Appearance.
 * The right side shows the selected section's content. Only functionality
 * supported by the backend is wired; unsupported persistence is surfaced
 * honestly.
 */
"use client";

import { useState, useEffect, useId } from "react";
import { AppShell } from "@/components/layout";
import { useTheme, type Theme } from "@/components/theme";
import {
  getAuthUser,
  getDevSession,
  isDevAuthBypassEnabled,
} from "@/lib/auth";
import { cn } from "@/lib/utils";
import {
  User,
  SlidersHorizontal,
  Cpu,
  Bell,
  Palette,
} from "lucide-react";

type Section = "account" | "preferences" | "ai" | "notifications" | "appearance";

const SECTIONS: { id: Section; label: string; icon: typeof User }[] = [
  { id: "account", label: "Account", icon: User },
  { id: "preferences", label: "Preferences", icon: SlidersHorizontal },
  { id: "ai", label: "AI / Generation", icon: Cpu },
  { id: "notifications", label: "Notifications", icon: Bell },
  { id: "appearance", label: "Appearance", icon: Palette },
];

export default function SettingsPage() {
  const [section, setSection] = useState<Section>("account");

  return (
    <AppShell
      active="/settings"
      title="Settings"
      subtitle="Manage your account and preferences"
    >
      <div className="grid grid-cols-1 gap-6 md:grid-cols-[220px_1fr]">
        {/* Side navigation */}
        <nav
          aria-label="Settings sections"
          className="flex flex-row gap-1 overflow-x-auto md:flex-col"
        >
          {SECTIONS.map(({ id, label, icon: Icon }) => {
            const active = section === id;
            return (
              <button
                key={id}
                type="button"
                onClick={() => setSection(id)}
                className={cn(
                  "flex shrink-0 items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors",
                  active
                    ? "bg-accent font-medium text-foreground"
                    : "text-muted-foreground hover:bg-muted/50 hover:text-foreground",
                )}
                aria-current={active ? "page" : undefined}
              >
                <Icon className="h-4 w-4" aria-hidden="true" />
                {label}
              </button>
            );
          })}
        </nav>

        {/* Content */}
        <div className="min-w-0 rounded-xl border border-border bg-surface-elevated p-6">
          {section === "account" && <AccountSection />}
          {section === "preferences" && <PreferencesSection />}
          {section === "ai" && <AISection />}
          {section === "notifications" && <NotificationsSection />}
          {section === "appearance" && <AppearanceSection />}
        </div>
      </div>
    </AppShell>
  );
}

// --------------------------------------------------------------------------
// Sections
// --------------------------------------------------------------------------

function Field({ label, value, hint }: { label: string; value: string; hint?: string }) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-sm font-medium text-foreground">
        {label}
      </label>
      <input
        id={id}
        value={value}
        readOnly
        aria-label={label}
        className="input-base opacity-70"
      />
      {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

interface AccountIdentity {
  name: string;
  email: string;
  subtitle: string;
  development: boolean;
}

/**
 * Resolve the account shown in Settings truthfully:
 * - a real authenticated user (set by password login) takes priority,
 * - the explicit development identity is shown only when the development
 *   bypass is enabled (or a development session exists),
 * - an authenticated token without a stored identity never renders a fake
 *   "dev" persona.
 */
function resolveAccountIdentity(): AccountIdentity {
  const user = getAuthUser();
  if (user) {
    return {
      name: user.name,
      email: user.email,
      subtitle: "Signed in",
      development: false,
    };
  }

  const session = isDevAuthBypassEnabled() ? getDevSession() : null;
  if (session) {
    return {
      name: session.name,
      email: session.email,
      subtitle: "Development identity",
      development: true,
    };
  }

  return {
    name: "Signed in",
    email: "",
    subtitle: "Account",
    development: false,
  };
}

function AccountSection() {
  const identity = resolveAccountIdentity();
  return (
    <div className="space-y-5">
      <div>
        <h3 className="text-base font-semibold text-foreground">Profile</h3>
        <p className="text-xs text-muted-foreground">
          {identity.development
            ? "Your account is currently using the explicit development identity (dev mode)."
            : "This is the account you are signed in with."}
        </p>
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Name" value={identity.name} />
        <Field label="Email" value={identity.email || "—"} />
      </div>
      <div className="rounded-md border border-border bg-muted/30 px-4 py-3 text-xs text-muted-foreground">
        Password hashes are stored server-side (PBKDF2-SHA256). The frontend
        never sees or stores your password.
      </div>
    </div>
  );
}

function PreferencesSection() {
  return (
    <div className="space-y-5">
      <div>
        <h3 className="text-base font-semibold text-foreground">Preferences</h3>
        <p className="text-xs text-muted-foreground">
          Defaults that apply to your transformations.
        </p>
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <label
            htmlFor="settings-default-tone"
            className="mb-1 block text-sm font-medium text-foreground"
          >
            Default tone
          </label>
          <select id="settings-default-tone" className="input-base">
            <option>Professional</option>
            <option>Conversational</option>
            <option>Executive</option>
            <option>Technical</option>
            <option>Persuasive</option>
            <option>Concise</option>
          </select>
        </div>
        <div>
          <label
            htmlFor="settings-default-audience"
            className="mb-1 block text-sm font-medium text-foreground"
          >
            Default audience
          </label>
          <select id="settings-default-audience" className="input-base">
            <option>General</option>
            <option>Executives</option>
            <option>Technical</option>
            <option>Customers</option>
            <option>Investors</option>
            <option>Internal Team</option>
          </select>
        </div>
        <div>
          <label
            htmlFor="settings-language"
            className="mb-1 block text-sm font-medium text-foreground"
          >
            Language
          </label>
          <input
            id="settings-language"
            value="English"
            readOnly
            aria-label="Language"
            className="input-base opacity-70"
          />
        </div>
      </div>
      <div className="rounded-md border border-border bg-muted/30 px-4 py-3 text-xs text-muted-foreground">
        These preferences are not yet persisted on the backend. Configure them
        per transformation for now.
      </div>
    </div>
  );
}

function AISection() {
  const [provider, setProvider] = useState<string>("server");

  useEffect(() => {
    if (typeof window !== "undefined") {
      const stored = localStorage.getItem("transformiq.llm_provider");
      if (stored) {
        setProvider(stored);
      }
    }
  }, []);

  const handleProviderChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const val = e.target.value;
    setProvider(val);
    if (typeof window !== "undefined") {
      localStorage.setItem("transformiq.llm_provider", val);
    }
  };

  return (
    <div className="space-y-5">
      <div>
        <h3 className="text-base font-semibold text-foreground">
          AI / Generation
        </h3>
        <p className="text-xs text-muted-foreground">
          Generation behaviour and grounding options.
        </p>
      </div>
      <div className="space-y-4">
        <div>
          <label
            htmlFor="settings-llm-provider"
            className="mb-1 block text-sm font-medium text-foreground"
          >
            LLM provider
          </label>
          <select
            id="settings-llm-provider"
            className="input-base"
            aria-label="LLM provider"
            value={provider}
            onChange={handleProviderChange}
          >
            <option value="server">Server-configured (OpenAI / Gemini / Fallback)</option>
            <option value="fake">Development (Fake - Testing Purpose)</option>
          </select>
          <p className="mt-1 text-xs text-muted-foreground">
            {provider === "fake"
              ? "Running in Testing Purpose mode: full orchestration and artifact generation run offline without external LLM API keys."
              : "Provider is configured server-side. API keys are never exposed to the browser."}
          </p>
        </div>
        <div>
          <label
            htmlFor="settings-source-grounding"
            className="mb-1 block text-sm font-medium text-foreground"
          >
            Source grounding
          </label>
          <select
            id="settings-source-grounding"
            className="input-base"
            aria-label="Source grounding"
          >
            <option>Auto</option>
            <option>Always on</option>
            <option>Off</option>
          </select>
        </div>
      </div>
      <div className="rounded-md border border-success/30 bg-success/5 px-4 py-3 text-xs text-success">
        All generation runs server-side. No credentials are stored or shown in
        the frontend.
      </div>
    </div>
  );
}

function NotificationsSection() {
  const [completed, setCompleted] = useState(true);
  const [failed, setFailed] = useState(true);
  const [system, setSystem] = useState(false);

  return (
    <div className="space-y-5">
      <div>
        <h3 className="text-base font-semibold text-foreground">
          Notifications
        </h3>
        <p className="text-xs text-muted-foreground">
          Choose what you&apos;d like to be notified about.
        </p>
      </div>
      <div className="space-y-3">
        <ToggleRow
          label="Transformation completed"
          checked={completed}
          onChange={setCompleted}
        />
        <ToggleRow
          label="Transformation failed"
          checked={failed}
          onChange={setFailed}
        />
        <ToggleRow
          label="System notifications"
          checked={system}
          onChange={setSystem}
        />
      </div>
      <div className="rounded-md border border-border bg-muted/30 px-4 py-3 text-xs text-muted-foreground">
        Notification delivery is not yet implemented on the backend. These
        preferences are stored locally only.
      </div>
    </div>
  );
}

function ToggleRow({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between rounded-md border border-border bg-background px-4 py-3">
      <span className="text-sm text-foreground">{label}</span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        onClick={() => onChange(!checked)}
        className={cn(
          "relative h-6 w-11 rounded-full transition-colors",
          checked ? "bg-primary" : "bg-muted",
        )}
      >
        <span
          className={cn(
            "absolute top-0.5 h-5 w-5 rounded-full bg-white transition-all",
            checked ? "left-[22px]" : "left-0.5",
          )}
        />
      </button>
    </div>
  );
}

function AppearanceSection() {
  const { theme, setTheme } = useTheme();
  const themes: { id: Theme; label: string }[] = [
    { id: "light", label: "Light" },
    { id: "dark", label: "Dark" },
    { id: "system", label: "System" },
  ];
  return (
    <div className="space-y-5">
      <div>
        <h3 className="text-base font-semibold text-foreground">Appearance</h3>
        <p className="text-xs text-muted-foreground">
          Choose how KaryaSetu AI looks on this device.
        </p>
      </div>
      <div role="radiogroup" aria-label="Theme" className="flex gap-2">
        {themes.map((t) => (
          <button
            key={t.id}
            type="button"
            role="radio"
            aria-checked={theme === t.id}
            onClick={() => setTheme(t.id)}
            className={cn(
              "rounded-md border px-4 py-2 text-sm transition-colors",
              theme === t.id
                ? "border-primary/60 bg-primary/10 font-medium text-primary"
                : "border-border bg-background text-muted-foreground hover:text-foreground",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className="rounded-md border border-border bg-muted/30 px-4 py-3 text-xs text-muted-foreground">
        Your choice is stored on this device and applied instantly.{" "}
        &ldquo;System&rdquo; follows the operating system preference and stays
        live as it changes.
      </div>
    </div>
  );
}
