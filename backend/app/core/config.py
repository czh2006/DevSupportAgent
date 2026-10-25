from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_name: str = "DevSupport Agent"
    app_env: Literal["development", "test", "production"] = "development"
    database_path: Path = BACKEND_DIR / "data" / "devsupport.db"

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        env_prefix="DEVSUPPORT_",
        extra="ignore",
    )


settings = Settings()