from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[1]


class DemoSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        env_prefix="DEMO_",
        extra="ignore",
    )

    database_path: Path = (
        BACKEND_DIR / "data" / "demo-requests.db"
    )

    api_key: SecretStr = SecretStr("demo-local-key")

    project_id: str = "demo-project"

    upstream_url: str = (
        "http://127.0.0.1:8011/v1/answer"
    )

    upstream_timeout_seconds: float = Field(
        default=2.0,
        gt=0,
    )

    rate_limit_requests: int = Field(
        default=3,
        ge=1,
    )

    rate_limit_window_seconds: float = Field(
        default=30.0,
        gt=0,
    )