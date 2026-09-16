"""Test env bootstrap: dummy settings so app modules import with no DB/network.

Must run before any `app.*` module is imported, since app/config.py builds a
module-level `Settings()` instance that fails fast on missing env vars.
"""
import os

from cryptography.fernet import Fernet

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-service-key")
os.environ.setdefault("SUPABASE_BUCKET", "menu-catalog")
os.environ.setdefault("SESSION_SECRET", "x" * 32)
os.environ.setdefault("FERNET_KEY", Fernet.generate_key().decode())
os.environ.setdefault("APP_USERS", '[{"username":"test","password":"test"}]')
os.environ.setdefault("STORAGE_BACKEND", "local")
os.environ.setdefault("LOCAL_STORAGE_DIR", "./_storage_test")
