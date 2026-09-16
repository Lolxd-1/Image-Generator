/// screens/generate/GenerateBanners.tsx — the three notices above the tile
/// grid: the always-on "keep this tab open" warning (SPEC.md §9, a real
/// architecture constraint the admin must be told up front), the job-level
/// failure banner (only for AuthFailure per SPEC.md §6 — never for a single
/// item_failed), and a rate-limit backoff notice — driven by the server's
/// `backingOff`/`waitMs`, with a live countdown — so a silent multi-minute
/// pause never reads as a frozen app.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Card } from "../../components/Card";

export function KeepTabOpenBanner() {
  return (
    <Card className="border-warn-600/40 bg-warn-600/5">
      <p className="text-sm font-medium text-warn-400">
        Keep this tab open — closing it pauses the run.
      </p>
      <p className="text-xs text-base-400">
        Nothing is lost: reopen this page and it continues exactly where it stopped.
      </p>
    </Card>
  );
}

export function JobFailedBanner({ shopId, message }: { shopId?: string; message: string }) {
  return (
    <Card className="border-danger-600/50 bg-danger-600/5">
      <p className="text-sm font-medium text-danger-400">The run stopped: job failed</p>
      <p className="text-xs text-base-400">{message}</p>
      <Link to={`/shops/${shopId}/review`} className="text-xs text-accent-400 underline">
        Back to review
      </Link>
    </Card>
  );
}

/** `waitMs` is the server's authoritative wait for the step currently pending;
 * this counts it down locally so the banner reads as "waiting", not "hung". */
export function BackingOffBanner({ waitMs }: { waitMs: number | null }) {
  const [remainingMs, setRemainingMs] = useState(waitMs ?? 0);

  useEffect(() => {
    setRemainingMs(waitMs ?? 0);
    if (waitMs === null) return undefined;
    const startedAt = Date.now();
    const id = window.setInterval(() => {
      setRemainingMs(Math.max(0, waitMs - (Date.now() - startedAt)));
    }, 1000);
    return () => window.clearInterval(id);
  }, [waitMs]);

  return (
    <Card className="border-warn-600/40 bg-warn-600/5">
      <p className="text-sm text-warn-400">
        Slowing down on purpose — the free-tier API quota rate-limited a recent request.
        Resuming automatically in {formatCountdown(remainingMs)}. This is not a hang.
      </p>
    </Card>
  );
}

function formatCountdown(ms: number): string {
  const totalSeconds = Math.ceil(ms / 1000);
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}
