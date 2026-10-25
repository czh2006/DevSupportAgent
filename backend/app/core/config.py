from pathlib import Path
from typing import Literal
from pydantic import Field, SecretStr, model_validator

from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_name: str = "DevSupport Agent"
    app_env: Literal["development", "test", "production"] = "development"
    database_path: Path = BACKEND_DIR / "data" / "devsupport.db"
    llm_enabled: bool = False
    llm_api_key: SecretStr | None = None
    llm_base_url: str | None = None
    llm_model: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        env_prefix="DEVSUPPORT_",
        extra="ignore",
    )
    @model_validator(mode="after")
    def validate_llm_configuration(self) -> "Settings":
        if not self.llm_enabled:
            return self

        missing_fields: list[str] = []

        if self.llm_api_key is None:
            missing_fields.append("DEVSUPPORT_LLM_API_KEY")

        if self.llm_base_url is None:
            missing_fields.append("DEVSUPPORT_LLM_BASE_URL")

        if self.llm_model is None:
            missing_fields.append("DEVSUPPORT_LLM_MODEL")

        if missing_fields:
            missing_names = ", ".join(missing_fields)
            raise ValueError(
                f"启用 LLM 时必须配置：{missing_names}"
            )

        return self


settings = Settings()