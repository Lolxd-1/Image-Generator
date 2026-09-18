/// lib/generateLoop.ts — the client-side driver for the generate job's
/// /step loop (SPEC.md §7). This is the file the whole generation run
/// depends on: every dish image gets produced by repeated calls this hook
/// schedules, so its timing and concurrency guarantees matter more than
/// almost anything else in the frontend.
//
// Contract
// --------
//  - The backend leases one API key per in-flight /step call and tells the
//    client, via StepResult, how many concurrent lanes to run (`lanes`) and
//    how long THIS lane should wait before its own next step
//    (`next_step_ms`). useGenerateLoop(jobId, lanes) starts `lanes ?? 1`
//    independent lanes (capped at 6), each POSTing /api/jobs/{id}/step on
//    its own schedule. Lanes start staggered by 300ms so they don't all hit
//    the server in the same millisecond and fight over the same first key.
//  - Per lane, based on the response `status`:
//      "generated"                -> wait next_step_ms (falls back to
//                                    next_delay_ms), step again
//      "rate_limited" | "waiting" -> wait next_step_ms (falls back to
//                                    retry_after_ms), step again
//      "item_failed"              -> ONE dish gave up; wait and CONTINUE.
//                                    One bad dish must never halt a 100-item
//                                    run.
//      "complete" | "failed"      -> stop the WHOLE loop, every lane; no
//                                    further step is scheduled ("failed" is
//                                    job-level only: AuthFailure)
//    A wait is floored at 250ms when non-zero; 0 means "step immediately".
//    (This hook owns only the stepping. Screens poll job status and the
//    event log via `useJob`/`useJobEvents` from api/hooks.ts independently.)
//  - If a response's `lanes` exceeds the number of lanes currently running,
//    a key was added mid-run: extra lanes are spun up (staggered, capped at
//    6 total). If it's lower, the surplus lanes stop after their current
//    step rather than being cut off mid-request.
//  - An ApiError with code "job_not_running" means another lane already
//    completed or failed the job: stop the whole loop silently (`error`
//    stays null). Any other error stops only that ONE lane; if it was the
//    last lane still running, stop the loop and set `error`.
//  - `runningRef` is a ref, not state: start() reads it synchronously, so a
//    second start() call — whether from a double click before a re-render,
//    or a React StrictMode double-invoked effect — is a no-op whenever a
//    loop is already active. It is now the RUN guard for the whole loop;
//    each lane additionally guards against double-stepping itself via its
//    own inFlight flag.
//  - pause() clears the guard and every lane's pending timer. It does not
//    cancel an in-flight fetch (the underlying POST already reached the
//    server and claimed/released an item there), but it prevents any
//    response — including ones already in flight — from scheduling a
//    further step.
//  - Unmounting runs the same cleanup as pause(), plus marks the instance
//    unmounted so a response that arrives after unmount cannot call setState
//    or schedule a new timer.
//  - done/failed/remaining always mirror the counters the LAST server
//    response returned (they are server counters, so a later response
//    supersedes an earlier one) rather than anything accumulated
//    client-side. waitMs reports the wait of whichever lane most recently
//    responded.
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
  /** The wait of whichever lane most recently responded, in ms. */
  waitMs: number | null;
  /** True while the server is telling us to back off after a 429. */
  backingOff: boolean;
  /** Name of the dish the last step worked on, for a "now generating" line. */
  lastItemName: string | null;
  /** The number of lanes actually running right now. */
  lanes: number;
  /** How many of those lanes have a /step request in flight right now. */
  activeLanes: number;
  /** Distinct key hints seen this run, newest first, capped at 8. */
  keyHints: string[];
  start: () => void;
  pause: () => void;
}

const DEFAULT_RETRY_MS = 1000;
const STAGGER_MS = 300;
const MAX_LANES = 6;
const MAX_KEY_HINTS = 8;

function normalizeWait(ms: number): number {
  return ms > 0 ? Math.max(250, ms) : 0;
}

export function useGenerateLoop(jobId: string | undefined, lanes?: number): GenerateLoopState {
  const [running, setRunning] = useState(false);
  const [done, setDone] = useState(0);
  const [failed, setFailed] = useState(0);
  const [remaining, setRemaining] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [lastStatus, setLastStatus] = useState<StepStatus | null>(null);
  const [waitMs, setWaitMs] = useState<number | null>(null);
  const [lastItemName, setLastItemName] = useState<string | null>(null);
  const [laneCount, setLaneCount] = useState(0);
  const [activeLaneCount, setActiveLaneCount] = useState(0);
  const [keyHints, setKeyHints] = useState<string[]>([]);

  // Ref-based RUN guard: is the loop running at all (not per-lane).
  const runningRef = useRef(false);
  // Bumped by start()/stopAll(). A lane captures this before its fetch and
  // discards the response if it no longer matches: a pause() followed by a
  // start() reuses the same lane indices and re-sets runningRef, so that
  // guard alone cannot tell a stale in-flight response (from the paused run)
  // apart from a fresh one (from the run the user just restarted).
  const runIdRef = useRef(0);
  // Desired number of lanes right now (grows/shrinks with the server's `lanes`).
  const laneTargetRef = useRef(0);
  // Indices of lanes currently started (may or may not have a request in
  // flight or a timer pending right now).
  const laneAliveRef = useRef<Set<number>>(new Set());
  // Indices of lanes with a /step request currently in flight.
  const laneInFlightRef = useRef<Set<number>>(new Set());
  // Per-lane pending timer handle.
  const laneTimersRef = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map());
  const mountedRef = useRef(true);
  const jobIdRef = useRef(jobId);
  jobIdRef.current = jobId;

  const clearLaneTimer = useCallback((i: number) => {
    const t = laneTimersRef.current.get(i);
    if (t !== undefined) {
      clearTimeout(t);
      laneTimersRef.current.delete(i);
    }
  }, []);

  const clearAllTimers = useCallback(() => {
    for (const t of laneTimersRef.current.values()) clearTimeout(t);
    laneTimersRef.current.clear();
  }, []);

  const updateActiveLanes = useCallback(() => {
    if (mountedRef.current) setActiveLaneCount(laneInFlightRef.current.size);
  }, []);

  const stopLane = useCallback(
    (i: number) => {
      laneAliveRef.current.delete(i);
      laneInFlightRef.current.delete(i);
      clearLaneTimer(i);
      if (mountedRef.current) setLaneCount(laneAliveRef.current.size);
    },
    [clearLaneTimer],
  );

  const stopAll = useCallback(() => {
    runningRef.current = false;
    runIdRef.current += 1;
    laneTargetRef.current = 0;
    clearAllTimers();
    laneAliveRef.current.clear();
    laneInFlightRef.current.clear();
    if (mountedRef.current) {
      setRunning(false);
      setLaneCount(0);
      setActiveLaneCount(0);
    }
  }, [clearAllTimers]);

  const addKeyHint = useCallback((hint: string) => {
    if (!mountedRef.current) return;
    setKeyHints((prev) => {
      if (prev[0] === hint) return prev;
      return [hint, ...prev.filter((h) => h !== hint)].slice(0, MAX_KEY_HINTS);
    });
  }, []);

  // stepLane/scheduleLane/launchLane are mutually recursive; stepLane is
  // invoked through a ref so scheduleLane/launchLane can close over it
  // without a forward-reference error (one lane's worth of the old
  // step/scheduleStep pattern, per lane now).
  const stepLaneRef = useRef<(i: number) => Promise<void>>();

  const scheduleLane = useCallback(
    (i: number, delayMs: number) => {
      clearLaneTimer(i);
      if (!runningRef.current || !laneAliveRef.current.has(i)) return;
      const t = setTimeout(() => {
        laneTimersRef.current.delete(i);
        void stepLaneRef.current?.(i);
      }, normalizeWait(delayMs));
      laneTimersRef.current.set(i, t);
    },
    [clearLaneTimer],
  );

  const launchLane = useCallback((i: number, staggerMs: number) => {
    laneAliveRef.current.add(i);
    if (mountedRef.current) setLaneCount(laneAliveRef.current.size);
    const t = setTimeout(() => {
      laneTimersRef.current.delete(i);
      void stepLaneRef.current?.(i);
    }, staggerMs);
    laneTimersRef.current.set(i, t);
  }, []);

  const reconcileLanes = useCallback(
    (serverLanes: number) => {
      if (!runningRef.current) return;
      const target = Math.min(Math.max(1, Math.trunc(serverLanes)), MAX_LANES);
      laneTargetRef.current = target;
      if (target > laneAliveRef.current.size) {
        let stagger = 0;
        for (let idx = 0; idx < target; idx++) {
          if (!laneAliveRef.current.has(idx)) {
            launchLane(idx, stagger * STAGGER_MS);
            stagger++;
          }
        }
      }
    },
    [launchLane],
  );

  const stepLane = useCallback(
    async (i: number) => {
      if (!runningRef.current || !laneAliveRef.current.has(i)) return;
      if (i >= laneTargetRef.current) {
        // The target shrank while this lane's timer was pending — let it
        // stop instead of stepping again.
        stopLane(i);
        return;
      }
      if (laneInFlightRef.current.has(i)) return; // guard: this lane is already stepping

      const id = jobIdRef.current;
      if (!id) return;

      const runId = runIdRef.current;
      laneInFlightRef.current.add(i);
      updateActiveLanes();

      let result: StepResult;
      try {
        result = await post<StepResult>(`/jobs/${id}/step`);
      } catch (err) {
        if (runId !== runIdRef.current) return; // a paused/restarted run — not ours to handle
        laneInFlightRef.current.delete(i);
        updateActiveLanes();
        if (!mountedRef.current || !runningRef.current || !laneAliveRef.current.has(i)) return;

        if (err instanceof ApiError && err.code === "job_not_running") {
          // Another lane already completed/failed the job — stop silently.
          setError(null);
          stopAll();
          return;
        }

        // Any other error stops only this one lane.
        stopLane(i);
        if (laneAliveRef.current.size === 0) {
          setError(err instanceof ApiError ? err.message : "Step request failed");
          stopAll();
        }
        return;
      }

      if (runId !== runIdRef.current) return; // stale response from a paused/restarted run
      laneInFlightRef.current.delete(i);
      updateActiveLanes();
      if (!mountedRef.current || !runningRef.current || !laneAliveRef.current.has(i)) return;

      setDone(result.done);
      setFailed(result.failed);
      setRemaining(result.remaining);
      // Only a JOB-level abort is an error. A single dish failing is expected
      // attrition on a flaky free-tier quota and must not surface as a failure.
      setError(result.status === "failed" ? (result.item?.error ?? "Job failed") : null);

      const status: StepStatus = result.status;
      setLastStatus(status);
      if (result.item?.name) setLastItemName(result.item.name);
      if (result.key_hint) addKeyHint(result.key_hint);

      if (
        status === "generated" ||
        status === "item_failed" ||
        status === "rate_limited" ||
        status === "waiting"
      ) {
        reconcileLanes(result.lanes);
        if (i >= laneTargetRef.current) {
          // This lane is surplus now that the target has shrunk — stop it
          // after this step instead of scheduling another.
          stopLane(i);
          return;
        }
        const wait =
          status === "generated" || status === "item_failed"
            ? (result.next_step_ms ?? result.next_delay_ms ?? 0)
            : (result.next_step_ms ?? result.retry_after_ms ?? DEFAULT_RETRY_MS);
        setWaitMs(wait);
        scheduleLane(i, wait);
      } else {
        // "complete" or "failed" — stop the WHOLE loop, not just this lane.
        setWaitMs(null);
        stopAll();
      }
    },
    [addKeyHint, reconcileLanes, scheduleLane, stopAll, stopLane, updateActiveLanes],
  );

  stepLaneRef.current = stepLane;

  const start = useCallback(() => {
    if (runningRef.current) return; // RUN guard: a loop is already active
    if (!jobIdRef.current) return;
    const L = Math.min(Math.max(1, lanes ?? 1), MAX_LANES);
    runningRef.current = true;
    runIdRef.current += 1;
    laneTargetRef.current = L;
    setRunning(true);
    setError(null);
    setKeyHints([]);
    for (let i = 0; i < L; i++) launchLane(i, i * STAGGER_MS);
  }, [lanes, launchLane]);

  const pause = useCallback(() => {
    stopAll();
  }, [stopAll]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      runningRef.current = false;
      laneTargetRef.current = 0;
      clearAllTimers();
      laneAliveRef.current.clear();
      laneInFlightRef.current.clear();
    };
  }, [clearAllTimers]);

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
    lanes: laneCount,
    activeLanes: activeLaneCount,
    keyHints,
    start,
    pause,
  };
}
