/**
 * TransformIQ — Security activity log (Phase 12D-G).
 *
 * Read-only view of the bounded security events the backend recorded for the
 * authenticated owner (events the user initiated or events belonging to
 * projects they own).  It surfaces what the operationally relevant controls
 * did — malware scans, PII detections, integrity recording, authentication
 * denials — without exposing source content, credentials, secrets, or other
 * users' activity.
 */
"use client";

import { useEffect, useState } from "react";
import {
  type SecurityEventResponse,
  operationsApi,
  ApiError,
} from "@/lib/api";
import { StatusBadge, type BadgeVariant } from "@/components/common";
import { formatDateTime } from "@/lib/outputTypes";
import { Activity, Loader2 } from "lucide-react";

interface SecurityActivityProps {
  projectId?: string;
  limit?: number;
}

const MAX_EVENTS = 100;

function outcomeVariant(outcome: string): BadgeVariant {
  switch (outcome) {
    case "allowed":
      return "success";
    case "denied":
      return "error";
    default:
      return "muted";
  }
}

export function SecurityActivity({
  projectId,
  limit = 20,
}: SecurityActivityProps) {
  const [events, setEvents] = useState<SecurityEventResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    operationsApi
      .securityEvents({
        projectId,
        limit: Math.max(1, Math.min(limit, MAX_EVENTS)),
      })
      .then((res) => {
        if (!cancelled) setEvents(res.data);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(
          err instanceof ApiError
            ? err.detail
            : "Security activity could not be loaded.",
        );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, limit]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
        Loading security activity…
      </div>
    );
  }

  if (error) {
    return (
      <p role="alert" className="text-xs font-medium text-destructive">
        {error}
      </p>
    );
  }

  const list = events ?? [];

  return (
    <div className="rounded-md border border-border bg-muted/30 px-3 py-2">
      <div className="flex items-center justify-between gap-2">
        <p className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
          <Activity className="h-3.5 w-3.5" aria-hidden="true" />
          Security activity
        </p>
        <span className="text-[10px] text-muted-foreground">
          {list.length} event{list.length !== 1 ? "s" : ""}
        </span>
      </div>

      {list.length === 0 ? (
        <p className="mt-2 text-[11px] text-muted-foreground">
          No security events recorded for your scope yet.
        </p>
      ) : (
        <ul className="mt-2 max-h-72 space-y-1 overflow-auto pr-1">
          {list.map((event, index) => (
            <li
              key={`${event.timestamp}-${event.event_type}-${index}`}
              className="flex items-center gap-2 rounded-md border border-border/60 bg-muted/40 px-2 py-1.5 text-[11px]"
            >
              <StatusBadge
                variant={outcomeVariant(event.outcome)}
                className="shrink-0"
              >
                {event.outcome}
              </StatusBadge>
              <span className="font-medium text-foreground">
                {event.event_type}
              </span>
              {event.reason && (
                <span className="truncate text-muted-foreground">
                  — {event.reason}
                </span>
              )}
              <span className="ml-auto shrink-0 text-muted-foreground">
                {formatDateTime(event.timestamp)}
              </span>
            </li>
          ))}
        </ul>
      )}

      <p className="mt-2 text-[10px] text-muted-foreground">
        Read-only, owner-scoped, bounded events — no content, credentials, or
        secrets.
      </p>
    </div>
  );
}