"""Application settings loaded from environment variables (pydantic-settings)."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str
    SUPABASE_URL: str
    SUPABASE_SERVICE_KEY: str
    SUPABASE_BUCKET: str = "menu-catalog"
    SESSION_SECRET: str
    FERNET_KEY: str
    APP_USERS: str
    STORAGE_BACKEND: str = "supabase"
    LOCAL_STORAGE_DIR: str = "./_storage"

    # Injected by the host at build time, so /api/health can report exactly
    # which commit is serving. Render sets RENDER_GIT_COMMIT; the others are
    # the equivalents on hosts we might move to. Empty when run locally.
    RENDER_GIT_COMMIT: str = ""
    KOYEB_GIT_SHA: str = ""
    SOURCE_COMMIT: str = ""
    GIT_COMMIT: str = ""

    @property
    def build_commit(self) -> str:
        for v in (self.RENDER_GIT_COMMIT, self.KOYEB_GIT_SHA,
                  self.SOURCE_COMMIT, self.GIT_COMMIT):
            if v:
                return v[:7]
        return "unknown"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
