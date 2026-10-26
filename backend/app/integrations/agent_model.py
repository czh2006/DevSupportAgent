from contextlib import asynccontextmanager

import httpx
from langchain_openai import ChatOpenAI

from app.core.config import settings


@asynccontextmanager
async def open_agent_model():
    if (
        not settings.llm_enabled
        or settings.llm_api_key is None
        or settings.llm_base_url is None
        or settings.llm_model is None
    ):
        raise RuntimeError("Agent model is not configured.")

    async with httpx.AsyncClient(
        trust_env=False,
        timeout=20,
    ) as http:
        yield ChatOpenAI(
            api_key=settings.llm_api_key.get_secret_value(),
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            temperature=0,
            timeout=20,
            max_retries=0,
            max_tokens=800,
            http_async_client=http,
            extra_body={
                "thinking": {
                    "type": "disabled",
                }
            },
        )