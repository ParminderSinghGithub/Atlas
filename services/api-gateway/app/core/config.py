"""
Configuration for API Gateway.

Environment variables:
- USER_SERVICE_URL: Downstream user service base URL
- CATALOG_SERVICE_URL: Downstream catalog service base URL
- RECOMMENDATION_SERVICE_URL: Downstream recommendation service base URL
"""
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