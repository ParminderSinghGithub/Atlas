"""
Configuration management using Pydantic Settings.
Environment variables override defaults.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Database
    DATABASE_URL: str = "postgresql://postgres:postgres@db:5432/ecommerce"
    
    # Service
    SERVICE_NAME: str = "catalog-service"
    SERVICE_PORT: int = 5004
    LOG_LEVEL: str = "INFO"
    
    # API
    API_V1_PREFIX: str = "/api/v1/catalog"
    
    # Pagination
    DEFAULT_PAGE_SIZE: int = 20
    MAX_PAGE_SIZE: int = 100
    
    # Currency conversion (USD to INR)
    USD_TO_INR_RATE: float = 83.0
    
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True
    )


settings = Settings()
