/// lib/generateLoop.ts — the client-side driver for the generate job's
/// /step loop (SPEC.md §7). This is the file the whole generation run
/// depends on: every dish image gets produced by repeated calls this hook
/// schedules, so its timing and concurrency guarantees matter more than
/// almost anything else in the frontend.
//
// Contract
// --------
//  - start() POSTs /api/jobs/{id}/step once, then — based on the response
//    `status` — decides what happens next:
//      "generated"                -> wait `next_delay_ms`, step again
//      "rate_limited" | "waiting" -> wait `retry_after_ms`, step again
//      "item_failed"              -> ONE dish gave up; wait next_delay_ms and
//                                    CONTINUE. One bad dish must never halt a
//                                    100-item run.
//      "complete" | "failed"      -> stop; no further step is scheduled
//                                    ("failed" is job-level only: AuthFailure)
//    (This hook owns only the stepping. Screens poll job status and the event
//    log via `useJob`/`useJobEvents` from api/hooks.ts independently.)
//  - `runningRef` is a ref, not state: start() reads it synchronously, so a
//    second start() call — whether from a double click before a re-render,
//    or a React StrictMode double-invoked effect — is a no-op whenever a
//    loop is already active. At most one step is ever in flight and at most
//    one timer is ever pending per hook instance.
//  - pause() clears the guard and any pending timer. It does not cancel an
//    in-flight fetch (the underlying POST already reached the server and
//    claimed/released an item there), but it prevents that response from
//    scheduling a further step.
//  - Unmounting runs the same cleanup as pause(), plus marks the instance
//    unmounted so a response that arrives after unmount cannot call setState
//    or schedule a new timer.
//  - done/failed/remaining always mirror the counters the server just
//    returned, so the UI reflects true server-side progress rather than
//    anything counted client-side.
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, post } from "../api/client";
import type { StepResult, StepStatus } from "../api/types";

export interface GenerateLoopState {
  running: boolean;
  done: number;
  failed: number;
  remaining: number;
  /** Extra beyond the SPEC.md §7 signature: surfaces the last step error, if any. */
  error: string | null;
  /**
   * The last status the server returned. The UI needs this to distinguish a
   * deliberate back-off from a hang: a 300s pause with no explanation looks
   * exactly like a frozen app.
   */
  lastStatus: StepStatus | null;
  /** The server's authoritative wait before the next step, in ms. */
  waitMs: number | null;
  /** True while the server is telling us to back off after a 429. */
  backingOff: boolean;
  /** Name of the dish the last step worked on, for a "now generating" line. */
  lastItemName: string | null;
  start: () => void;
  pause: () => void;
}

const DEFAULT_RETRY_MS = 1000;

export function useGenerateLoop(jobId: string | undefined): GenerateLoopState {
  const [running, setRunning] = useState(false);
  const [done, setDone] = useState(0);
  const [failed, setFailed] = useState(0);
  const [remaining, setRemaining] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [lastStatus, setLastStatus] = useState<StepStatus | null>(null);
  const [waitMs, setWaitMs] = useState<number | null>(null);
  const [lastItemName, setLastItemName] = useState<string | null>(null);

  // Ref-based guard: prevents two concurrent loops for this hook instance.
  const runningRef = useRef(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);
  const jobIdRef = useRef(jobId);
  jobIdRef.current = jobId;

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const stop = useCallback(() => {
    runningRef.current = false;
    clearTimer();
    if (mountedRef.current) setRunning(false);
  }, [clearTimer]);

  // step/scheduleStep are mutually recursive; declared with `let` so each
  // can close over the other without a forward-reference error.
  const stepRef = useRef<() => Promise<void>>();

  const scheduleStep = useCallback(
    (delayMs: number) => {
      clearTimer();
      timerRef.current = setTimeout(() => {
        timerRef.current = null;
        void stepRef.current?.();
      }, Math.max(0, delayMs));
    },
    [clearTimer],
  );

  const step = useCallback(async () => {
    const id = jobIdRef.current;
    if (!id || !runningRef.current) return;

    let result: StepResult;
    try {
      result = await post<StepResult>(`/jobs/${id}/step`);
    } catch (err) {
      if (!mountedRef.current || !runningRef.current) return;
      setError(err instanceof ApiError ? err.message : "Step request failed");
      stop();
      return;
    }

    if (!mountedRef.current || !runningRef.current) return;

    setDone(result.done);
    setFailed(result.failed);
    setRemaining(result.remaining);
    // Only a JOB-level abort is an error. A single dish failing is expected
    // attrition on a flaky free-tier quota and must not surface as a failure.
    setError(result.status === "failed" ? (result.item?.error ?? "Job failed") : null);

    const status: StepStatus = result.status;
    setLastStatus(status);
    if (result.item?.name) setLastItemName(result.item.name);

    if (status === "generated" || status === "item_failed") {
      const wait = result.next_delay_ms ?? 0;
      setWaitMs(wait);
      scheduleStep(wait);
    } else if (status === "rate_limited" || status === "waiting") {
      const wait = result.retry_after_ms ?? DEFAULT_RETRY_MS;
      setWaitMs(wait);
      scheduleStep(wait);
    } else if (status === "complete" || status === "failed") {
      setWaitMs(null);
      stop();
    }
  }, [scheduleStep, stop]);

  stepRef.current = step;

  const start = useCallback(() => {
    if (runningRef.current) return; // guard: a loop is already active
    if (!jobIdRef.current) return;
    runningRef.current = true;
    setRunning(true);
    setError(null);
    void step();
  }, [step]);

  const pause = useCallback(() => {
    stop();
  }, [stop]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      runningRef.current = false;
      clearTimer();
    };
  }, [clearTimer]);

  return {
    running,
    done,
    failed,
    remaining,
    error,
    lastStatus,
    waitMs,
    backingOff: lastStatus === "rate_limited",
    lastItemName,
    start,
    pause,
  };
}
