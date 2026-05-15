"""
Configuration for API Gateway.

Environment variables:
- USER_SERVICE_URL: Downstream user service base URL
- CATALOG_SERVICE_URL: Downstream catalog service base URL
- RECOMMENDATION_SERVICE_URL: Downstream recommendation service base URL
"""
import os
from urllib.parse import urlparse

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    USER_SERVICE_URL: str = "http://user-service:5000"
    CATALOG_SERVICE_URL: str = "http://catalog-service:5004"
    RECOMMENDATION_SERVICE_URL: str = "http://recommendation-service:5005"

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()


def _normalize_service_url(url: str) -> str:
    """Normalize service base URLs for proxy construction."""
    normalized = url.strip().rstrip("/")
    if normalized.endswith("/api/v1"):
        normalized = normalized[: -len("/api/v1")].rstrip("/")
    if normalized.endswith("/api"):
        normalized = normalized[: -len("/api")].rstrip("/")
    return normalized


def get_recommendation_service_url() -> str:
    """Return the normalized recommendation service base URL."""
    return _normalize_service_url(settings.RECOMMENDATION_SERVICE_URL)


def get_recommendation_service_url_source() -> str:
    """Describe whether recommendation URL came from env or default fallback."""
    raw_env = os.getenv("RECOMMENDATION_SERVICE_URL")
    if raw_env is None:
        return f"default fallback ({settings.RECOMMENDATION_SERVICE_URL})"
    if not raw_env.strip():
        return "empty environment override"
    return "environment override"


def validate_service_url(url: str, setting_name: str) -> None:
    """Fail fast on empty or protocol-less downstream URLs."""
    if not url:
        raise ValueError(f"{setting_name} resolved to an empty string")

    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"{setting_name} must include protocol and host: {url!r}")