import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_allows_disabled_llm_without_model_configuration() -> None:
    settings = Settings(
        llm_enabled=False,
    )

    assert settings.llm_enabled is False
    assert settings.llm_api_key is None
    assert settings.llm_base_url is None
    assert settings.llm_model is None


def test_rejects_incomplete_enabled_llm_configuration() -> None:
    with pytest.raises(ValidationError) as error:
        Settings(
            llm_enabled=True,
            llm_model="qwen-plus",
        )

    assert "DEVSUPPORT_LLM_API_KEY" in str(error.value)
    assert "DEVSUPPORT_LLM_BASE_URL" in str(error.value)


def test_allows_complete_enabled_llm_configuration() -> None:
    settings = Settings(
        llm_enabled=True,
        llm_api_key="test-api-key",
        llm_base_url="https://example.com/v1",
        llm_model="test-model",
    )

    assert settings.llm_enabled is True
    assert settings.llm_api_key is not None
    assert settings.llm_api_key.get_secret_value() == "test-api-key"
    assert settings.llm_base_url == "https://example.com/v1"
    assert settings.llm_model == "test-model"