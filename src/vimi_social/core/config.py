from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VIMI_", env_file=".env", extra="ignore")

    env: str = "development"
    database_dsn: str = "postgresql+psycopg://vimi_app@localhost:5432/vimi"
    temporal_target: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "vimi-social"
    media_task_queue: str = "vimi-social-media"
    destination_task_queue: str = "vimi-social-destination"
    media_root: str = ".vimi-media"
    media_max_bytes: int = 64 * 1024 * 1024
    object_storage_endpoint: str = "http://localhost:9000"
    object_storage_bucket: str = "vimi-media"
    otel_service_name: str = "vimi-social"
    telegram_bot_token: str | None = None
    telegram_webhook_secret: str | None = None
    x_bearer_token: str | None = None
    local_ai_url: str | None = None
    local_ai_timeout_seconds: float = 20.0
    semantic_relevance_min_score: float = 0.18
    allow_paid_ai_fallback: bool = False
    search_translation_api_key: str | None = None
    search_translation_model: str = "gpt-6-luna"
    openai_api_key: str | None = None
    visual_moderation_model: str = "omni-moderation-latest"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
