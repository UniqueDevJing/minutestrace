from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MINUTESTRACE_", env_file=".env", extra="ignore")

    app_name: str = "MinutesTrace"
    api_prefix: str = "/minutestrace/api"
    database_url: str = "sqlite:///./data/minutestrace.db"
    jwt_secret: str = "dev-only-change-me-minutestrace"
    jwt_ttl_minutes: int = 720
    storage_dir: Path = Path("./data/uploads")
    public_base_url: str = "http://127.0.0.1:8000/minutestrace/api"
    upload_limit_mb: int = 512
    llm_api_key: str = ""
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    llm_model: str = "qwen-plus"
    asr_base_url: str = "https://dashscope.aliyuncs.com/api/v1"
    asr_model: str = "paraformer-v2"
    demo_password: str = "demo123456"
    worker_stale_seconds: int = 180
    ffmpeg_path: str = "ffmpeg"
    environment: str = "development"

    @property
    def max_upload_bytes(self) -> int:
        return self.upload_limit_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    return settings
