/**
 * TransformIQ — Dashboard home page (Phase 9)
 *
 * Shows platform identity, service connectivity status, and a link into the
 * transformation workspace (projects).
 */
"use client";

import { useEffect, useState } from "react";
import { DashboardLayout } from "@/components/layout";
import {
  LoadingSpinner,
  ErrorState,
  StatusBadge,
} from "@/components/common";
import { healthApi, type HealthResponse, type ReadyResponse, ApiError } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ServiceStatus = "loading" | "ok" | "degraded" | "error";

interface ServiceState {
  status: ServiceStatus;
  detail?: string;
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function HomePage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [ready, setReady] = useState<ReadyResponse | null>(null);
  const [backendStatus, setBackendStatus] = useState<ServiceState>({
    status: "loading",
  });

  useEffect(() => {
    let cancelled = false;

    async function checkServices() {
      // Health check
      try {
        const h = await healthApi.health();
        if (!cancelled) {
          setHealth(h);
          setBackendStatus({ status: "ok" });
        }
      } catch (err) {
        if (!cancelled) {
          const msg =
            err instanceof ApiError
              ? err.detail
              : "Backend unreachable";
          setBackendStatus({ status: "error", detail: msg });
        }
      }

      // Readiness check (separate — backend may be up but deps not ready)
      try {
        const r = await healthApi.ready();
        if (!cancelled) setReady(r);
      } catch {
        // readiness failure is non-fatal here — shown in the checks table
      }
    }

    checkServices();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <DashboardLayout>
      <div className="space-y-8">
        {/* ---------------------------------------------------------------- */}
        {/* Hero section                                                     */}
        {/* ---------------------------------------------------------------- */}
        <section className="space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-3xl font-bold tracking-tight text-foreground">
              TransformIQ
            </h1>
            <StatusBadge variant="info">Phase 9 — Workspace</StatusBadge>
          </div>
          <p className="max-w-2xl text-base text-muted-foreground">
            Gen AI Platform for Automated Content Transformation.{" "}
            <span className="text-foreground/70">SIH Problem Statement 26154.</span>
          </p>
          <p className="max-w-2xl text-sm text-muted-foreground">
            One source → Content Intelligence → Canonical Content →
            Configurable Transformation → Multiple Outputs → Verification → Export.
          </p>
          <a
            href="/projects"
            className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            Open transformation workspace
            <svg
              aria-hidden="true"
              xmlns="http://www.w3.org/2000/svg"
              className="h-4 w-4"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M13.5 4.5 21 12m0 0-7.5 7.5M21 12H3"
              />
            </svg>
          </a>
        </section>

        {/* ---------------------------------------------------------------- */}
        {/* Service connectivity panel                                       */}
        {/* ---------------------------------------------------------------- */}
        <section className="space-y-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Service Connectivity
          </h2>

          {backendStatus.status === "loading" && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <LoadingSpinner size="sm" />
              Checking backend…
            </div>
          )}

          {backendStatus.status === "error" && (
            <ErrorState
              message={`Backend unreachable — ${backendStatus.detail}`}
              onRetry={() => {
                setBackendStatus({ status: "loading" });
                setHealth(null);
                setReady(null);
                // re-mount effect by changing key is not available here;
                // just do another fetch inline
                healthApi.health()
                  .then((h) => {
                    setHealth(h);
                    setBackendStatus({ status: "ok" });
                  })
                  .catch((err) => {
                    const msg = err instanceof ApiError ? err.detail : "Backend unreachable";
                    setBackendStatus({ status: "error", detail: msg });
                  });
                healthApi.ready()
                  .then(setReady)
                  .catch(() => undefined);
              }}
              className="max-w-lg"
            />
          )}

          {backendStatus.status === "ok" && health && (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <ServiceCard
                name="Backend API"
                status="ok"
                detail={`v${health.version} · ${health.environment}`}
                href="http://localhost:8000/health"
                linkLabel="/health"
              />
              <ServiceCard
                name="API Docs"
                status="ok"
                detail="OpenAPI / Swagger UI"
                href="http://localhost:8000/docs"
                linkLabel="/docs"
              />
              <ServiceCard
                name="Database"
                status={
                  ready?.checks?.database === "ok"
                    ? "ok"
                    : ready?.checks?.database === "unavailable"
                      ? "error"
                      : "pending"
                }
                detail={ready?.checks?.database ?? "checking…"}
              />
              <ServiceCard
                name="Redis"
                status={
                  ready?.checks?.redis === "ok"
                    ? "ok"
                    : ready?.checks?.redis === "unavailable"
                      ? "error"
                      : "pending"
                }
                detail={ready?.checks?.redis ?? "checking…"}
              />
            </div>
          )}
        </section>

        {/* ---------------------------------------------------------------- */}
        {/* MVP output types                                                 */}
        {/* ---------------------------------------------------------------- */}
        <section className="space-y-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Supported Output Types
          </h2>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              { label: "Executive Summary", note: "Text" },
              { label: "LinkedIn Post", note: "Text" },
              { label: "Advisory", note: "Text" },
              { label: "Presentation", note: "PPTX" },
              { label: "Infographic", note: "PNG + PDF" },
              { label: "Video", note: "PDF + SRT" },
              { label: "X Post", note: "Text" },
            ].map((item) => (
              <div
                key={item.label}
                className="rounded-lg border border-dashed border-border bg-muted/30 p-4"
              >
                <p className="text-sm font-medium text-foreground">
                  {item.label}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {item.note}
                </p>
              </div>
            ))}
          </div>
          <p className="text-xs text-muted-foreground">
            Open a project to select outputs, generate, and download.
          </p>
        </section>

        {/* ---------------------------------------------------------------- */}
        {/* Uptime detail (shown only when health data is available)         */}
        {/* ---------------------------------------------------------------- */}
        {health && (
          <section className="rounded-lg border border-border bg-muted/30 p-4">
            <p className="text-xs text-muted-foreground">
              Backend uptime:{" "}
              <span className="font-medium text-foreground">
                {health.uptime_seconds}s
              </span>{" "}
              · environment:{" "}
              <span className="font-medium text-foreground">
                {health.environment}
              </span>
            </p>
          </section>
        )}
      </div>
    </DashboardLayout>
  );
}

// ---------------------------------------------------------------------------
// Service card sub-component
// ---------------------------------------------------------------------------

type CardStatus = "ok" | "error" | "pending" | "loading";

interface ServiceCardProps {
  name: string;
  status: CardStatus;
  detail: string;
  href?: string;
  linkLabel?: string;
}

const cardVariants: Record<CardStatus, string> = {
  ok: "border-green-200 bg-green-50 dark:border-green-800 dark:bg-green-950/20",
  error: "border-destructive/30 bg-destructive/10",
  pending: "border-yellow-200 bg-yellow-50 dark:border-yellow-800 dark:bg-yellow-950/20",
  loading: "border-border bg-muted/30",
};

const dotVariants: Record<CardStatus, string> = {
  ok: "bg-green-500",
  error: "bg-destructive",
  pending: "bg-yellow-500",
  loading: "bg-muted-foreground/40",
};

function ServiceCard({ name, status, detail, href, linkLabel }: ServiceCardProps) {
  return (
    <div className={`rounded-lg border p-4 ${cardVariants[status]}`}>
      <div className="mb-1 flex items-center gap-2">
        <span className={`h-2 w-2 rounded-full ${dotVariants[status]}`} />
        <span className="text-sm font-medium text-foreground">{name}</span>
      </div>
      {href ? (
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground"
        >
          {linkLabel ?? detail}
        </a>
      ) : (
        <p className="text-xs text-muted-foreground">{detail}</p>
      )}
    </div>
  );
}
