/**
 * TransformIQ — Reusable async polling hook.
 *
 * Polls a fetcher on an interval until a terminal condition is met.
 * Guarantees:
 *   - asynchronous (never blocks the UI)
 *   - no overlapping requests (an in-flight request defers the next tick)
 *   - stops on terminal state and on error
 *   - timers are cleaned up on unmount / stop
 *   - safe under Strict Mode (idempotent start/stop cleanup)
 */
import { useCallback, useEffect, useRef, useState } from "react";

export type PollPhase = "idle" | "polling" | "done" | "error";

export interface UsePollingOptions<T> {
  /** Async fetcher invoked on every tick. */
  fetcher: () => Promise<T>;
  /** Returns true when polling should stop with a result. */
  isDone: (data: T) => boolean;
  /** Delay between polls in milliseconds. */
  intervalMs?: number;
  /** When true, polling starts automatically. */
  enabled?: boolean;
  /** Changing this value restarts the polling loop from scratch. */
  resetKey?: unknown;
  /** Invoked when polling ends on an error. */
  onError?: (error: unknown) => void;
  /** Invoked when polling ends on a terminal result. */
  onDone?: (data: T) => void;
}

export interface UsePollingResult<T> {
  data: T | null;
  phase: PollPhase;
  /** The last non-null error, if polling errored. */
  error: unknown;
  /** Begin polling (safe to call repeatedly). */
  start: () => void;
  /** Stop polling and clear timers. */
  stop: () => void;
  /** Trigger a single immediate poll without changing the loop. */
  refresh: () => void;
}

export function usePolling<T>(
  options: UsePollingOptions<T>,
): UsePollingResult<T> {
  const {
    fetcher,
    isDone,
    intervalMs = 2000,
    enabled = true,
    resetKey,
    onError,
    onDone,
  } = options;

  const [data, setData] = useState<T | null>(null);
  const [phase, setPhase] = useState<PollPhase>("idle");
  const [error, setError] = useState<unknown>(null);

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inFlightRef = useRef(false);
  const activeRef = useRef(false);

  const fetcherRef = useRef(fetcher);
  const isDoneRef = useRef(isDone);
  const onErrorRef = useRef(onError);
  const onDoneRef = useRef(onDone);
  const intervalMsRef = useRef(intervalMs);

  useEffect(() => {
    fetcherRef.current = fetcher;
  }, [fetcher]);
  useEffect(() => {
    isDoneRef.current = isDone;
  }, [isDone]);
  useEffect(() => {
    onErrorRef.current = onError;
  }, [onError]);
  useEffect(() => {
    onDoneRef.current = onDone;
  }, [onDone]);
  useEffect(() => {
    intervalMsRef.current = intervalMs;
  }, [intervalMs]);

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const tick = useCallback(async () => {
    if (!activeRef.current || inFlightRef.current) return;
    inFlightRef.current = true;
    try {
      const result = await fetcherRef.current();
      if (!activeRef.current) return;
      setError(null);
      setData(result);

      if (isDoneRef.current(result)) {
        activeRef.current = false;
        clearTimer();
        setPhase("done");
        onDoneRef.current?.(result);
        return;
      }

      setPhase("polling");
      if (activeRef.current) {
        timerRef.current = setTimeout(() => {
          void tickRef.current();
        }, intervalMsRef.current);
      }
    } catch (err) {
      if (!activeRef.current) return;
      activeRef.current = false;
      clearTimer();
      setError(err);
      setPhase("error");
      onErrorRef.current?.(err);
    } finally {
      inFlightRef.current = false;
    }
  }, [clearTimer]);

  const tickRef = useRef(tick);
  useEffect(() => {
    tickRef.current = tick;
  }, [tick]);

  const start = useCallback(() => {
    activeRef.current = true;
    setError(null);
    setPhase("polling");
    clearTimer();
    timerRef.current = setTimeout(() => {
      void tickRef.current();
    }, 0);
  }, [clearTimer]);

  const stop = useCallback(() => {
    activeRef.current = false;
    clearTimer();
    setPhase("idle");
  }, [clearTimer]);

  const refresh = useCallback(() => {
    if (!activeRef.current) return;
    clearTimer();
    void tickRef.current();
  }, [clearTimer]);

  useEffect(() => {
    if (enabled) {
      start();
    } else {
      stop();
    }
    return () => {
      // Cleanup on unmount or when enabled/resetKey changes.
      activeRef.current = false;
      clearTimer();
    };
  }, [enabled, resetKey, start, stop, clearTimer]);

  return { data, phase, error, start, stop, refresh };
}