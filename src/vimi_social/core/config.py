from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VIMI_", env_file=".env", extra="ignore")

    env: str = "development"
    database_dsn: str = (
        "postgresql+psycopg://vimi_app:vimi_app_local@localhost:5432/vimi"
    )
    temporal_target: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "vimi-social"
    object_storage_endpoint: str | None = None
    object_storage_bucket: str = "vimi-media"
    otel_service_name: str = Field(default="vimi-social")


@lru_cache
def get_settings() -> Settings:
    return Settings()
