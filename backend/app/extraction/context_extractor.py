import re

from app.schemas.context import RuntimeEnvironment
from app.schemas.context_suggestion import ContextCandidate


REQUEST_ID_PATTERN = re.compile(
    r"(?i)(?:请求\s*(?:id|编号)|request\s*(?:id|identifier)|"
    r"req(?:uest)?\s*id)\s*(?:是|为|:|：|=)?\s*"
    r"([A-Za-z0-9][A-Za-z0-9_-]{2,127})"
)

REQUEST_ID_FALLBACK_PATTERN = re.compile(
    r"(?i)(?<![\w-])(req_[A-Za-z0-9_-]{3,127})(?![\w-])"
)

HTTP_STATUS_PATTERN = re.compile(
    r"(?i)(?:http\s*(?:状态码|status(?:\s*code)?)|状态码|"
    r"返回|报错|错误)\s*(?:是|为|:|：|=)?\s*"
    r"([1-5]\d{2})(?!\d)"
)

API_VERSION_PATTERN = re.compile(
    r"(?i)(?:api\s*)?(v\d+(?:\.\d+)?)(?![\w.])"
)

ENVIRONMENT_KEYWORDS: tuple[
    tuple[RuntimeEnvironment, tuple[str, ...]],
    ...,
] = (
    (
        RuntimeEnvironment.PRODUCTION,
        ("生产环境", "production"),
    ),
    (
        RuntimeEnvironment.STAGING,
        ("预发环境", "预发布环境", "staging"),
    ),
    (
        RuntimeEnvironment.LOCAL,
        ("本地环境", "本地", "local"),
    ),
)

REQUIRED_CONTEXT_FIELDS = (
    "api_version",
    "environment",
    "request_id",
    "http_status_code",
)


def extract_context_candidate(content: str) -> ContextCandidate:
    evidence: dict[str, str] = {}

    request_id, request_id_evidence = extract_request_id(content)
    if request_id_evidence is not None:
        evidence["request_id"] = request_id_evidence

    http_status_code, http_status_evidence = extract_http_status_code(
        content,
    )
    if http_status_evidence is not None:
        evidence["http_status_code"] = http_status_evidence

    api_version, api_version_evidence = extract_api_version(content)
    if api_version_evidence is not None:
        evidence["api_version"] = api_version_evidence

    environment, environment_evidence = extract_environment(content)
    if environment_evidence is not None:
        evidence["environment"] = environment_evidence

    values = {
        "api_version": api_version,
        "environment": environment,
        "request_id": request_id,
        "http_status_code": http_status_code,
    }

    missing_fields = [
        field_name
        for field_name in REQUIRED_CONTEXT_FIELDS
        if values[field_name] is None
    ]

    return ContextCandidate(
        api_version=api_version,
        environment=environment,
        request_id=request_id,
        http_status_code=http_status_code,
        evidence=evidence,
        missing_fields=missing_fields,
    )


def extract_request_id(
    content: str,
) -> tuple[str | None, str | None]:
    match = REQUEST_ID_PATTERN.search(content)

    if match is None:
        match = REQUEST_ID_FALLBACK_PATTERN.search(content)

    if match is None:
        return None, None

    return match.group(1), match.group(0)


def extract_http_status_code(
    content: str,
) -> tuple[int | None, str | None]:
    match = HTTP_STATUS_PATTERN.search(content)

    if match is None:
        return None, None

    return int(match.group(1)), match.group(0)


def extract_api_version(
    content: str,
) -> tuple[str | None, str | None]:
    match = API_VERSION_PATTERN.search(content)

    if match is None:
        return None, None

    return match.group(1).lower(), match.group(0)


def extract_environment(
    content: str,
) -> tuple[RuntimeEnvironment | None, str | None]:
    normalized_content = content.lower()

    for environment, keywords in ENVIRONMENT_KEYWORDS:
        for keyword in keywords:
            if keyword in normalized_content:
                return environment, keyword

    return None, None