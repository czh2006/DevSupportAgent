from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from app.core.config import settings
from app.schemas.context_suggestion import LlmContextExtraction

import httpx

from langchain_core.exceptions import OutputParserException
from langchain_core.runnables import Runnable
from openai import APIError, APITimeoutError
from pydantic import ValidationError

from app.extraction.errors import LlmExtractionError


CONTEXT_EXTRACTION_PROMPT = """
你是开发者故障排查系统中的信息提取组件。

任务：从用户输入中提取明确提到的排障上下文。

字段定义：
- api_version：明确出现的 API 版本，例如 v1、v2、v1.1。
- environment：local、staging 或 production。
- request_id：明确出现的请求编号。
- http_status_code：明确出现的 HTTP 状态码。

规则：
1. 只提取用户明确表达的信息，不要根据经验猜测。
2. 每个非空字段必须在 evidence 中提供用户原文的连续片段。
3. evidence 的值必须完全来自用户输入，不得改写、翻译或编造。
4. 无法确定时返回 null。
5. confidence 必须在 0 到 1 之间。
6. 不要把“被限流”自动转换为 429；除非用户明确写出了 429。
7. “线上”或 “prod” 可以规范化为 production，但 evidence 必须保留原始表达。
8. “测试环境”含义不明确，不要自动映射为 staging。
9. 证据应尽可能短，只引用支持当前字段的必要原文。
10. environment 的 evidence 应只引用环境词本身，
    例如“线上”“prod”“预发环境”，不要引用整句话。
11. http_status_code 和 api_version 的证据中，
    不要混入其他请求的状态码或版本。
12. 用户可能使用词表之外的环境说法。明确指现有环境时，
    可以给出标准枚举值，并保留原始 evidence。
    如果可能是 QA、开发集群等独立环境，或含义模糊，
    environment 返回 null，并在 evidence 的 environment 项保留原词。

用户输入：
{content}
"""

class ContextModelAdapter:
    def __init__(
        self,
        chain: Runnable[dict[str, str], LlmContextExtraction],
    ) -> None:
        self.chain = chain

    def invoke(
        self,
        payload: dict[str, str],
    ) -> LlmContextExtraction:
        try:
            result = self.chain.invoke(payload)

            return LlmContextExtraction.model_validate(result)

        except (APITimeoutError, httpx.TimeoutException) as exc:
            raise LlmExtractionError("llm_timeout") from exc

        except (APIError, httpx.HTTPError) as exc:
            raise LlmExtractionError("llm_unavailable") from exc

        except (OutputParserException, ValidationError) as exc:
            raise LlmExtractionError("llm_invalid_output") from exc


def create_llm_context_model():
    if not settings.llm_enabled:
        raise RuntimeError("LLM 当前未启用")

    if (
        settings.llm_api_key is None
        or settings.llm_base_url is None
        or settings.llm_model is None
    ):
        raise RuntimeError("LLM 配置不完整")

    chat_model = ChatOpenAI(
        api_key=settings.llm_api_key.get_secret_value(),
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        temperature=0,
        timeout=20,
        max_retries=0,
    )

    prompt = ChatPromptTemplate.from_template(
        CONTEXT_EXTRACTION_PROMPT,
    )

    structured_model = chat_model.with_structured_output(
        LlmContextExtraction,
    )

    return ContextModelAdapter(prompt | structured_model)