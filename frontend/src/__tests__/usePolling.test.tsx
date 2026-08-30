/**
 * Phase 9 tests — usePolling hook.
 *
 * Verifies async polling without overlapping requests, terminal-state stop,
 * restart on resetKey change, error handling, and timer cleanup on unmount.
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { usePolling, type UsePollingOptions } from "@/hooks/usePolling";

type Payload = { value: number };

const sleep = () => new Promise((r) => setTimeout(r, 0));

describe("usePolling", () => {
  it("polls until the terminal condition and calls onDone", async () => {
    let ticks = 0;
    const fetcher = jest.fn(async () => {
      ticks += 1;
      return { value: ticks };
    });
    const onDone = jest.fn();

    const { result } = renderHook(() =>
      usePolling<Payload>({
        intervalMs: 30,
        enabled: true,
        resetKey: "r",
        isDone: (d) => d.value >= 3,
        fetcher,
        onDone,
      }),
    );

    await waitFor(() => expect(result.current.phase).toBe("done"), {
      timeout: 2000,
    });
    expect(fetcher).toHaveBeenCalledTimes(3);
    expect(onDone).toHaveBeenCalled();
  });

  it("never overlaps requests when responses are slow", async () => {
    let inFlight = 0;
    let maxInFlight = 0;
    let ticks = 0;
    const fetcher = jest.fn(async () => {
      inFlight += 1;
      maxInFlight = Math.max(maxInFlight, inFlight);
      await sleep();
      ticks += 1;
      inFlight -= 1;
      return { value: ticks };
    });

    renderHook(() =>
      usePolling<Payload>({
        intervalMs: 10,
        enabled: true,
        resetKey: "r",
        isDone: (d) => d.value >= 5,
        fetcher,
      }),
    );

    await waitFor(() => expect(ticks).toBeGreaterThanOrEqual(5), {
      timeout: 3000,
    });
    expect(maxInFlight).toBe(1);
  });

  it("restarts polling when resetKey changes", async () => {
    const fetcher = jest.fn(async () => ({ value: 1 }));
    const onDone = jest.fn();

    const props = { resetKey: "first" };
    const { result, rerender } = renderHook(
      ({ resetKey }: { resetKey: string }) =>
        usePolling<Payload>({
          intervalMs: 20,
          enabled: true,
          resetKey,
          isDone: (d) => d.value >= 1,
          fetcher,
          onDone,
        }),
      { initialProps: props },
    );

    await waitFor(() => expect(result.current.phase).toBe("done"), {
      timeout: 2000,
    });
    expect(onDone).toHaveBeenCalledTimes(1);

    act(() => {
      rerender({ resetKey: "second" });
    });
    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(2), {
      timeout: 2000,
    });
  });

  it("reports errors through onError and stops polling", async () => {
    const onError = jest.fn();
    const fetcher = jest.fn(async () => {
      throw new Error("boom");
    });

    const { result } = renderHook(() =>
      usePolling<Payload>({
        intervalMs: 20,
        enabled: true,
        resetKey: "r",
        isDone: () => false,
        fetcher,
        onError,
      }),
    );

    await waitFor(() => expect(result.current.phase).toBe("error"), {
      timeout: 2000,
    });
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(onError).toHaveBeenCalled();
  });

  it("does nothing while disabled", async () => {
    const fetcher = jest.fn(async () => ({ value: 0 }));
    renderHook(() =>
      usePolling<Payload>({
        intervalMs: 20,
        enabled: false,
        resetKey: "r",
        isDone: () => false,
        fetcher,
      }),
    );
    await sleep();
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("cleans up its timer when unmounted (no stray fetches)", async () => {
    const fetcher = jest.fn(async () => ({ value: 0 }));
    const { unmount } = renderHook(() =>
      usePolling<Payload>({
        intervalMs: 20,
        enabled: true,
        resetKey: "r",
        isDone: () => false,
        fetcher,
      }),
    );
    unmount();
    await sleep();
    expect(fetcher).not.toHaveBeenCalled();
  });
});