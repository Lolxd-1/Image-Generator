/// screens/Generate.tsx — drives the /step loop for a generate Job via
/// useGenerateLoop (lib/generateLoop.ts) and shows a live tile grid.
//
// Pacing and backoff are read straight from the server via useGenerateLoop's
// waitMs/backingOff/lastStatus/lastItemName fields — no client-side
// inference. ETA is waitMs * remaining, not an observed rate.
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  useActiveJob,
  useApiKeys,
  useItems,
  useJob,
  useJobEvents,
  useRegenerateItem,
} from "../api/hooks";
import { useGenerateLoop } from "../lib/generateLoop";
import { Button } from "../components/Button";
import { EmptyState } from "../components/EmptyState";
import { Spinner } from "../components/Spinner";
import { BackingOffBanner, JobFailedBanner, KeepTabOpenBanner } from "./generate/GenerateBanners";
import { GenerateTile } from "./generate/GenerateTile";
import { LogDrawer } from "./generate/LogDrawer";
import { ProgressPanel } from "./generate/ProgressPanel";
import { clearStoredJobId, getStoredJobId, setStoredJobId } from "./generate/jobStorage";

const ACTIVE_STATUSES = new Set(["queued", "generating", "generated", "hosted", "failed"]);

export default function Generate() {
  const { id: shopId } = useParams<{ id: string }>();
  const [search] = useSearchParams();
  const queryJobId = search.get("job") ?? undefined;

  // Server is the source of truth for "is a job running for this shop";
  // localStorage is only a fast path so the first render has something to
  // show before useActiveJob resolves.
  const activeJobQ = useActiveJob(shopId);
  const fastPathJobId = useMemo(
    () => queryJobId ?? (shopId ? getStoredJobId(shopId) ?? undefined : undefined),
    [queryJobId, shopId],
  );
  const [jobId, setJobId] = useState<string | undefined>(fastPathJobId);

  useEffect(() => {
    setJobId(fastPathJobId);
  }, [fastPathJobId]);

  useEffect(() => {
    if (queryJobId) return; // an explicit ?job= wins outright
    if (!shopId || activeJobQ.isLoading) return;
    if (activeJobQ.data) {
      setJobId(activeJobQ.data.id);
      setStoredJobId(shopId, activeJobQ.data.id);
    } else if (getStoredJobId(shopId)) {
      // Server says nothing is running; a stored id (if any) is stale.
      clearStoredJobId(shopId);
      setJobId(undefined);
    }
  }, [shopId, queryJobId, activeJobQ.isLoading, activeJobQ.data]);

  useEffect(() => {
    if (shopId && jobId) setStoredJobId(shopId, jobId);
  }, [shopId, jobId]);

  const jobQ = useJob(jobId, { refetchInterval: 4000 });
  const keysQ = useApiKeys();
  const enabledKeys = keysQ.data?.filter((k) => k.enabled) ?? [];
  const lanes = Math.min(Math.max(enabledKeys.length, 1), 6);
  const loop = useGenerateLoop(jobId, lanes);
  const itemsQ = useItems(shopId, {});
  const eventsQ = useJobEvents(jobId);
  const regenM = useRegenerateItem(shopId ?? "");

  const [logOpen, setLogOpen] = useState(false);

  const startedRef = useRef(false);
  useEffect(() => {
    if (startedRef.current || !jobId || jobQ.isLoading) return;
    if (jobQ.data && jobQ.data.status !== "running") return;
    startedRef.current = true;
    loop.start();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId, jobQ.isLoading, jobQ.data]);

  const progressed = loop.done + loop.failed;
  const done = progressed > 0 || loop.running ? loop.done : jobQ.data?.done ?? 0;
  const failed = progressed > 0 || loop.running ? loop.failed : jobQ.data?.failed ?? 0;
  const total = jobQ.data?.total ?? done + failed + loop.remaining;
  const remaining = loop.running || progressed > 0 ? loop.remaining : Math.max(total - done - failed, 0);
  // Divide by the lanes actually running once the loop is running (the
  // server may have grown/shrunk it from the key-derived estimate);
  // `|| lanes` only matters before start, when loop.lanes is still 0.
  const etaLanes = loop.running ? loop.lanes || lanes : lanes;
  const eta = loop.waitMs !== null ? Math.round((loop.waitMs * remaining) / 1000 / etaLanes) : null;

  const items = (itemsQ.data?.items ?? [])
    .filter((i) => ACTIVE_STATUSES.has(i.status))
    .sort((a, b) => a.position - b.position);

  const isComplete = !loop.running && (jobQ.data?.status === "done" || (progressed > 0 && remaining === 0));
  const jobLevelFailed = jobQ.data?.status === "failed" || loop.error;

  if (!jobId) {
    return (
      <div className="p-6">
        <EmptyState
          title="No generation run to show"
          description="Start generation from the Review screen first."
          action={
            <Link to={`/shops/${shopId}/review`}>
              <Button size="sm">Go to review</Button>
            </Link>
          }
        />
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-4 p-6">
      <KeepTabOpenBanner />

      {jobLevelFailed && (
        <JobFailedBanner
          shopId={shopId}
          message={loop.error ?? jobQ.data?.error ?? "The job reported an unrecoverable error."}
        />
      )}

      {loop.backingOff && !jobLevelFailed && <BackingOffBanner waitMs={loop.waitMs} />}

      <p className="text-xs text-base-400">
        {lanes} lane{lanes === 1 ? "" : "s"} running on {enabledKeys.length} key
        {enabledKeys.length === 1 ? "" : "s"}
      </p>

      <ProgressPanel
        done={done}
        failed={failed}
        remaining={remaining}
        total={total}
        running={loop.running}
        isComplete={isComplete}
        waitMs={loop.waitMs}
        etaSeconds={eta}
        lastItemName={loop.lastItemName}
        onPause={loop.pause}
        onResume={loop.start}
      />

      <LogDrawer
        open={logOpen}
        onToggle={() => setLogOpen((v) => !v)}
        events={eventsQ.data}
        loading={eventsQ.isLoading}
      />

      {itemsQ.isLoading ? (
        <div className="flex h-40 items-center justify-center">
          <Spinner size={20} />
        </div>
      ) : items.length === 0 ? (
        <EmptyState title="No items queued for generation" />
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
          {items.map((item) => (
            <GenerateTile
              key={item.id}
              item={item}
              retrying={regenM.isPending && regenM.variables === item.id}
              onRetry={() => {
                regenM.mutate(item.id, {
                  onSuccess: () => {
                    if (!loop.running) loop.start();
                  },
                });
              }}
            />
          ))}
        </div>
      )}

      <div className="flex justify-end">
        <Link to={`/shops/${shopId}/catalog`}>
          <Button variant="ghost" size="sm">
            View catalog so far
          </Button>
        </Link>
      </div>
    </div>
  );
}
