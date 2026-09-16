/// screens/setup/ImgbbKeySection.tsx — the 4th required Setup input: the
/// shop's ImgBB key (SPEC.md §6 PUT /api/shops/{id}/imgbb-key). It is
/// stored encrypted server-side; Shop.has_imgbb_key is the only thing the
/// client ever sees back.
import { useState } from "react";
import type { FormEvent } from "react";
import { ApiError } from "../../api/client";
import { useSetImgbbKey } from "../../api/hooks";
import { Button } from "../../components/Button";
import { Card, CardHeader, CardTitle } from "../../components/Card";
import { Input } from "../../components/Input";

export function ImgbbKeySection({ shopId, hasKey }: { shopId: string; hasKey: boolean }) {
  const [replacing, setReplacing] = useState(false);
  const [key, setKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const setImgbbKey = useSetImgbbKey(shopId);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await setImgbbKey.mutateAsync({ key });
      setKey("");
      setReplacing(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save that key.");
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>ImgBB key</CardTitle>
      </CardHeader>
      <p className="mb-3 text-xs text-base-400">
        Used to host the final dish photos so they can be linked from the
        catalog export.
      </p>
      {hasKey && !replacing ? (
        <div className="flex items-center gap-2">
          <span className="text-xs text-base-300">A key is stored for this shop.</span>
          <Button size="sm" variant="secondary" onClick={() => setReplacing(true)}>
            Replace key
          </Button>
        </div>
      ) : (
        <form className="flex flex-col gap-2" onSubmit={onSubmit}>
          <Input
            label="ImgBB API key"
            type="password"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            required
          />
          {error && <p className="text-xs text-danger-400">{error}</p>}
          <div className="flex gap-2">
            <Button type="submit" size="sm" loading={setImgbbKey.isPending} disabled={!key.trim()}>
              Save key
            </Button>
            {hasKey && (
              <Button type="button" size="sm" variant="ghost" onClick={() => setReplacing(false)}>
                Cancel
              </Button>
            )}
          </div>
        </form>
      )}
    </Card>
  );
}
