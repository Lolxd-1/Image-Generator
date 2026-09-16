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

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
