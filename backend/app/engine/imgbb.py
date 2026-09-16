"""imgbb upload helper: turns image bytes into a public direct URL, ported from imgbb.py.

The retry loop and the code-111 "account is capped" detection are ported
verbatim from the original CLI tool's `upload()` — the cap check in particular
was hard-won (a 692-byte test image trips it just as reliably as a real one,
and retrying never helps). Unlike the original, this version is async (httpx),
takes the API key as an argument instead of reading `IMGBB_API_KEY`/a JSON
disk cache, and works on bytes rather than a file path.
"""
import asyncio
import base64

import httpx

API_URL = "https://api.imgbb.com/1/upload"
MAX_BYTES = 32 * 1024 * 1024      # imgbb hard limit
TIMEOUT = 60
PACE_SECONDS = 1.5                # caller should sleep this long between uploads
MAX_RETRIES = 4


class ImgbbUploadCap(RuntimeError):
    """imgbb is refusing every new upload for this key (HTTP 400, code 111).

    Distinct from an ordinary upload failure: nothing about the image is wrong
    and no amount of retrying will help, so a batch should stop rather than
    grind through the rest one doomed upload at a time.
    """


def is_upload_cap(body: str) -> bool:
    b = (body or "").lower()
    return '"code":111' in b.replace(" ", "") or "internal upload error" in b


async def upload(api_key: str, data: bytes, name: str) -> dict:
    """Upload one image and return {"url","display_url","delete_url"}.

    Raises `ImgbbUploadCap` on the account-level upload cap, `RuntimeError` on
    a bad key or on exhausting retries for any other failure.
    """
    if not data:
        raise RuntimeError(f"{name}: no image data to upload")
    size = len(data)
    if size > MAX_BYTES:
        raise RuntimeError(f"{name} is {size / 1e6:.1f} MB — over imgbb's 32 MB limit")

    payload = base64.b64encode(data).decode("ascii")

    last_err = ""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        for attempt in range(MAX_RETRIES):
            try:
                resp = await client.post(
                    API_URL,
                    data={"key": api_key, "image": payload, "name": name},
                )
            except Exception as e:
                last_err = f"{type(e).__name__}: {e}"
                await asyncio.sleep(min(3 * (2 ** attempt), 30))
                continue

            if resp.status_code == 200:
                try:
                    body = resp.json()["data"]
                except Exception as e:
                    last_err = f"unexpected response: {resp.text[:200]} ({e})"
                    break
                url = body.get("url") or body.get("display_url") or ""
                if url:
                    return {
                        "url": url,
                        "display_url": body.get("display_url", ""),
                        "delete_url": body.get("delete_url", ""),
                    }
                last_err = f"no url in response: {resp.text[:200]}"
                break

            # 400 with a bad key is permanent — don't burn retries on it.
            if resp.status_code == 400 and "key" in resp.text.lower():
                raise RuntimeError(f"imgbb rejected the API key: {resp.text[:200]}")

            # 400 / code 111 "Internal upload error" is imgbb's account-level
            # upload cap, not a problem with this file. Retrying harder never
            # helps, so surface it as its own error and let the caller stop
            # the whole batch instead of failing every image one at a time.
            if resp.status_code == 400 and is_upload_cap(resp.text):
                raise ImgbbUploadCap(
                    "imgbb is refusing all new uploads for this API key "
                    f"(HTTP 400, code 111). Response: {resp.text[:150]}"
                )

            last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"
            if resp.status_code in (429, 500, 502, 503, 504):
                await asyncio.sleep(min(5 * (2 ** attempt), 60))
                continue
            break

    raise RuntimeError(f"imgbb upload failed for {name} — {last_err}")
