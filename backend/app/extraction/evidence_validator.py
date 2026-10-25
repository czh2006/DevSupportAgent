import re

from app.schemas.context import RuntimeEnvironment


STATUS_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])([1-5][0-9]{2})(?![A-Za-z0-9_])"
)

VERSION_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_.])"
    r"(v[0-9]+(?:\.[0-9]+)*)"
    r"(?![A-Za-z0-9_.])",
    re.IGNORECASE,
)

ENVIRONMENT_ALIASES = {
    "线上": RuntimeEnvironment.PRODUCTION,
    "生产环境": RuntimeEnvironment.PRODUCTION,
    "production": RuntimeEnvironment.PRODUCTION,
    "prod": RuntimeEnvironment.PRODUCTION,
    "预发环境": RuntimeEnvironment.STAGING,
    "预发布环境": RuntimeEnvironment.STAGING,
    "staging": RuntimeEnvironment.STAGING,
    "本地": RuntimeEnvironment.LOCAL,
    "本地环境": RuntimeEnvironment.LOCAL,
    "local": RuntimeEnvironment.LOCAL,
}


def field_matches_evidence(
    field_name: str,
    value: object,
    evidence: str,
) -> bool:
    evidence = evidence.strip()

    if not evidence:
        return False

    if field_name == "http_status_code":
        if type(value) is not int:
            return False

        codes = {
            int(match)
            for match in STATUS_PATTERN.findall(evidence)
        }

        return codes == {value}

    if field_name == "api_version":
        if not isinstance(value, str):
            return False

        versions = {
            match.lower()
            for match in VERSION_PATTERN.findall(evidence)
        }

        return versions == {value.lower()}

    if field_name == "request_id":
        if not isinstance(value, str):
            return False

        if re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_-]{2,127}",
            value,
        ) is None:
            return False

        pattern = (
            r"(?<![A-Za-z0-9_-])"
            + re.escape(value)
            + r"(?![A-Za-z0-9_-])"
        )

        return re.search(pattern, evidence) is not None

    if field_name == "environment":
        expected_environment = ENVIRONMENT_ALIASES.get(
            evidence.lower(),
        )

        return (
            expected_environment is not None
            and expected_environment == value
        )

    return False