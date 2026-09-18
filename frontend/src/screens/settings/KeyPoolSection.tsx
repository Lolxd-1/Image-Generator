/// screens/settings/KeyPoolSection.tsx — paste/manage the 4-6 Gemini keys
/// that back the N-lane generate loop (T07). Mirrors
/// screens/setup/ImgbbKeySection.tsx for layout, copy and states.
import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { ApiError } from "../../api/client";
import {
  useAddApiKey,
  useApiKeys,
  useDeleteApiKey,
  useTestApiKey,
  useUpdateApiKey,
} from "../../api/hooks";
import type { ApiKey } from "../../api/types";
import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Card, CardHeader, CardTitle } from "../../components/Card";
import { EmptyState } from "../../components/EmptyState";
import { Input } from "../../components/Input";
import { Spinner } from "../../components/Spinner";
import { useToast } from "../../components/Toast";

const MAX_LANES = 6;

function keyErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === "conflict") return "That key is already in the pool.";
    if (err.code === "auth_failure") return "Gemini rejected this key.";
    if (err.code === "rate_limited") {
      return "Gemini is rate-limiting validation right now - try again in a moment.";
    }
    return err.message;
  }
  return "Something went wrong.";
}

/** Never show a pasted key verbatim, even in a failure list. */
function maskKey(key: string): string {
  if (key.length <= 8) return "•".repeat(key.length);
  return `${key.slice(0, 4)}…${key.slice(-4)}`;
}

function relativeTime(iso: string, nowMs: number): string {
  const s = Math.max(0, Math.round((nowMs - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.round(h / 24)}d ago`;
}

function availableInSeconds(nextAllowedAt: string | null, nowMs: number): number | null {
  if (!nextAllowedAt) return null;
  const diff = Math.round((new Date(nextAllowedAt).getTime() - nowMs) / 1000);
  return diff > 0 ? diff : null;
}

function ApiKeyRow({ apiKey, nowMs }: { apiKey: ApiKey; nowMs: number }) {
  const updateKey = useUpdateApiKey();
  const deleteKey = useDeleteApiKey();
  const testKey = useTestApiKey();
  const toast = useToast();
  const [editingLabel, setEditingLabel] = useState(false);
  const [labelDraft, setLabelDraft] = useState(apiKey.label);

  async function saveLabel(e: FormEvent) {
    e.preventDefault();
    try {
      await updateKey.mutateAsync({ id: apiKey.id, payload: { label: labelDraft.trim() } });
      setEditingLabel(false);
    } catch (err) {
      toast.show(keyErrorMessage(err), "error");
    }
  }

  async function toggleEnabled() {
    try {
      await updateKey.mutateAsync({ id: apiKey.id, payload: { enabled: !apiKey.enabled } });
    } catch (err) {
      toast.show(keyErrorMessage(err), "error");
    }
  }

  async function handleTest() {
    try {
      await testKey.mutateAsync(apiKey.id);
      toast.show("Key looks good", "success");
    } catch (err) {
      toast.show(keyErrorMessage(err), "error");
    }
  }

  async function handleDelete() {
    if (!window.confirm(`Delete the key "${apiKey.label || apiKey.key_hint}"? This can't be undone.`)) {
      return;
    }
    try {
      await deleteKey.mutateAsync(apiKey.id);
      toast.show("Key deleted", "success");
    } catch (err) {
      toast.show(keyErrorMessage(err), "error");
    }
  }

  const available = availableInSeconds(apiKey.next_allowed_at, nowMs);

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-base-800 py-2 last:border-0">
      <div className="flex min-w-[10rem] flex-1 flex-col gap-0.5">
        {editingLabel ? (
          <form className="flex items-center gap-1.5" onSubmit={saveLabel}>
            <Input
              value={labelDraft}
              onChange={(e) => setLabelDraft(e.target.value)}
              className="h-7 text-xs"
              autoFocus
            />
            <Button size="sm" type="submit" loading={updateKey.isPending}>
              Save
            </Button>
            <Button
              size="sm"
              variant="ghost"
              type="button"
              onClick={() => {
                setEditingLabel(false);
                setLabelDraft(apiKey.label);
              }}
            >
              Cancel
            </Button>
          </form>
        ) : (
          <button
            type="button"
            className="w-fit text-left text-sm font-medium text-base-100 hover:underline"
            onClick={() => setEditingLabel(true)}
          >
            {apiKey.label || "Untitled key"}
          </button>
        )}
        <span className="text-xs text-base-400">{apiKey.key_hint}</span>
        {!apiKey.enabled && apiKey.disabled_reason && (
          <span className="text-xs text-danger-400">{apiKey.disabled_reason}</span>
        )}
      </div>

      <div className="flex flex-col items-end gap-1 text-xs text-base-400">
        <div className="flex items-center gap-1.5">
          <Badge tone={apiKey.enabled ? "ok" : "neutral"}>{apiKey.enabled ? "Enabled" : "Disabled"}</Badge>
          {apiKey.busy && <Badge tone="accent">Busy</Badge>}
        </div>
        <span>{apiKey.last_used_at ? `Used ${relativeTime(apiKey.last_used_at, nowMs)}` : "Never used"}</span>
        <span>Pace {Math.round(apiKey.delay_s)}s</span>
        {available !== null && <span>Available in {available}s</span>}
      </div>

      <div className="flex gap-1.5">
        <Button
          size="sm"
          variant="secondary"
          loading={testKey.isPending && testKey.variables === apiKey.id}
          onClick={handleTest}
        >
          Test
        </Button>
        <Button
          size="sm"
          variant="secondary"
          loading={updateKey.isPending && updateKey.variables?.id === apiKey.id}
          onClick={toggleEnabled}
        >
          {apiKey.enabled ? "Disable" : "Enable"}
        </Button>
        <Button
          size="sm"
          variant="danger"
          loading={deleteKey.isPending && deleteKey.variables === apiKey.id}
          onClick={handleDelete}
        >
          Delete
        </Button>
      </div>
    </div>
  );
}

export function KeyPoolSection() {
  const keysQ = useApiKeys();
  const addKey = useAddApiKey();
  const toast = useToast();

  const [pasteText, setPasteText] = useState("");
  const [label, setLabel] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [multiResult, setMultiResult] = useState<{
    added: number;
    total: number;
    failures: { hint: string; reason: string }[];
  } | null>(null);
  const [adding, setAdding] = useState(false);

  const keys = keysQ.data ?? [];
  const enabledCount = keys.filter((k) => k.enabled).length;
  const lanes = Math.min(Math.max(enabledCount, 1), MAX_LANES);

  const anyPending = keys.some(
    (k) => k.busy || (k.next_allowed_at && new Date(k.next_allowed_at).getTime() > Date.now()),
  );
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    if (!anyPending) return;
    const t = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(t);
  }, [anyPending]);

  async function handleAdd(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    setMultiResult(null);
    const parts = pasteText.split(/[\n,]+/).map((s) => s.trim()).filter(Boolean);
    if (parts.length === 0) return;

    if (parts.length === 1) {
      setAdding(true);
      try {
        await addKey.mutateAsync({ key: parts[0], label: label.trim() || undefined });
        setPasteText("");
        setLabel("");
        toast.show("Key added", "success");
      } catch (err) {
        setFormError(keyErrorMessage(err));
      } finally {
        setAdding(false);
      }
      return;
    }

    // MULTI-PASTE: sequential, not parallel — each add is a live Gemini
    // validation call. The label field is ignored here (every key would
    // otherwise get the same name) so the server auto-names each "Key {n}".
    setAdding(true);
    let added = 0;
    const failures: { hint: string; reason: string }[] = [];
    for (const key of parts) {
      try {
        await addKey.mutateAsync({ key, label: undefined });
        added++;
      } catch (err) {
        failures.push({ hint: maskKey(key), reason: keyErrorMessage(err) });
      }
    }
    setAdding(false);
    setMultiResult({ added, total: parts.length, failures });
    if (added > 0) {
      setPasteText("");
      setLabel("");
    }
    toast.show(
      `Added ${added} of ${parts.length} keys`,
      added === parts.length ? "success" : added > 0 ? "info" : "error",
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Gemini key pool</CardTitle>
      </CardHeader>
      <p className="mb-1 text-xs text-base-300">
        {keys.length} keys · {enabledCount} enabled · up to {lanes} parallel lane{lanes === 1 ? "" : "s"}
      </p>
      <p className="mb-3 text-xs text-base-400">
        More keys let more images generate in parallel, capped at {MAX_LANES} lanes.
      </p>

      <form className="mb-4 flex flex-col gap-2" onSubmit={handleAdd}>
        <Input
          label="Paste one key, or several separated by commas or new lines"
          type="password"
          autoComplete="off"
          value={pasteText}
          onChange={(e) => setPasteText(e.target.value)}
          required
        />
        <Input label="Label (optional)" value={label} onChange={(e) => setLabel(e.target.value)} />
        {formError && <p className="text-xs text-danger-400">{formError}</p>}
        <div>
          <Button type="submit" size="sm" loading={adding} disabled={!pasteText.trim()}>
            Add key
          </Button>
        </div>
      </form>

      {multiResult && (
        <div className="mb-4 rounded-md border border-base-700 bg-base-800 p-2 text-xs text-base-300">
          <p>
            Added {multiResult.added} of {multiResult.total} keys.
          </p>
          {multiResult.failures.length > 0 && (
            <ul className="mt-1 list-disc pl-4">
              {multiResult.failures.map((f, i) => (
                <li key={i} className="text-danger-400">
                  {f.hint}: {f.reason}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {keysQ.isLoading ? (
        <div className="flex justify-center py-6">
          <Spinner size={20} />
        </div>
      ) : keys.length === 0 ? (
        <EmptyState
          title="No keys yet"
          description="Paste a Gemini API key above to start generating images."
        />
      ) : (
        <div className="flex flex-col">
          {keys.map((k) => (
            <ApiKeyRow key={k.id} apiKey={k} nowMs={nowMs} />
          ))}
        </div>
      )}
    </Card>
  );
}
