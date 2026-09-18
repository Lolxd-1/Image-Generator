"""Object storage abstraction: a Supabase bucket in prod, local filesystem for tests."""
import logging
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import anyio

from app.config import settings

logger = logging.getLogger(__name__)

_DELETE_MANY_BATCH = 100


class Storage(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...
    async def delete_many(self, keys: list[str]) -> None: ...


class SupabaseStorage:
    """Backed by the `supabase` python client. Its calls are blocking (httpx
    under the hood, called synchronously), so every call is pushed to a
    worker thread via anyio to keep the event loop free."""

    def __init__(self) -> None:
        from supabase import create_client

        self._client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
        self._bucket = settings.SUPABASE_BUCKET

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        def _put() -> None:
            self._client.storage.from_(self._bucket).upload(
                key, data, {"content-type": content_type, "upsert": "true"}
            )

        await anyio.to_thread.run_sync(_put)

    async def get(self, key: str) -> bytes:
        def _get() -> bytes:
            return self._client.storage.from_(self._bucket).download(key)

        return await anyio.to_thread.run_sync(_get)

    async def delete(self, key: str) -> None:
        def _delete() -> None:
            self._client.storage.from_(self._bucket).remove([key])

        await anyio.to_thread.run_sync(_delete)

    async def delete_many(self, keys: list[str]) -> None:
        def _delete_batch(batch: list[str]) -> None:
            try:
                self._client.storage.from_(self._bucket).remove(batch)
            except Exception:
                # A missing object must not abort a delete that has already
                # removed the DB rows that were the app's only reason to
                # care about it - but an orphaned blob needs a searchable
                # trace, so this is `error`, not `warning`.
                logger.error(
                    "delete_many: failed to remove a batch of %d objects, first key %s",
                    len(batch), batch[0], exc_info=True,
                )

        for i in range(0, len(keys), _DELETE_MANY_BATCH):
            batch = keys[i : i + _DELETE_MANY_BATCH]
            await anyio.to_thread.run_sync(_delete_batch, batch)


class LocalStorage:
    """Writes under settings.LOCAL_STORAGE_DIR. Used by tests and local dev."""

    def __init__(self) -> None:
        self._root = Path(settings.LOCAL_STORAGE_DIR)

    def _path(self, key: str) -> Path:
        # Keys are always the app-generated "shops/{id}/{kind}/{image_id}.jpg"
        # layout from SPEC §3 — never derived from user-controlled input.
        return self._root / key

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        def _put() -> None:
            path = self._path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

        await anyio.to_thread.run_sync(_put)

    async def get(self, key: str) -> bytes:
        def _get() -> bytes:
            return self._path(key).read_bytes()

        return await anyio.to_thread.run_sync(_get)

    async def delete(self, key: str) -> None:
        def _delete() -> None:
            path = self._path(key)
            if path.exists():
                path.unlink()

        await anyio.to_thread.run_sync(_delete)

    async def delete_many(self, keys: list[str]) -> None:
        def _delete_all() -> None:
            for key in keys:
                path = self._path(key)
                if path.exists():
                    path.unlink()

        await anyio.to_thread.run_sync(_delete_all)


@lru_cache(maxsize=1)
def get_storage() -> Storage:
    """Pick the storage backend from settings.STORAGE_BACKEND, once per process."""
    if settings.STORAGE_BACKEND == "local":
        return LocalStorage()
    return SupabaseStorage()
