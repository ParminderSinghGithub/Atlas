"""
Configuration for User Service.

Environment variables:
- POSTGRES_URI: PostgreSQL connection string
- JWT_SECRET: Secret key for JWT signing (must match Node.js service)
- JWT_ALGORITHM: JWT algorithm (default: HS256)
- JWT_EXPIRATION_HOURS: Token expiration (default: 1)
- RESET_TOKEN_EXPIRATION_MINUTES: Password reset token expiration (default: 15)
- SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM_EMAIL: Optional email settings
"""
from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Service
    service_name: str = "user-service"
    service_port: int = 5000
    
    # Database
    postgres_uri: str = "postgresql://postgres:postgres@db:5432/ecommerce"
    
    # JWT Configuration (MUST match Node.js service for compatibility)
    jwt_secret: str = "devsecret"
    jwt_algorithm: str = "HS256"  # MUST be HS256 for Node.js compatibility
    jwt_expiration_hours: int = 1  # 1 hour expiration
    
    # Password Reset & Recovery Configuration
    reset_token_expiration_minutes: int = 15
    
    # Optional SMTP Email Configuration
    smtp_host: Optional[str] = None
    smtp_port: int = 587
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_from_email: str = "noreply@atlas.local"
    smtp_use_tls: bool = True
    
    # Password Hashing
    bcrypt_rounds: int = 10
    
    class Config:
        env_file = ".env"
        case_sensitive = False


# Global settings instance
settings = Settings()
