"""
Configuration for Recommendation Service.

Environment variables:
- DATABASE_URL: PostgreSQL connection for latent_item_mappings
- REDIS_URL: Redis connection (optional)
- REDIS_ENABLED: Enable Redis caching (default: false)
- ARTIFACTS_PATH: Path to ML artifacts (default: /artifacts)
- MODEL_VERSION: Model version to load (default: latest)
- LOG_LEVEL: Logging level (default: INFO)
"""
from pydantic_settings import BaseSettings
from typing import Optional
from pathlib import Path


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Service
    service_name: str = "recommendation-service"
    service_port: int = 5005
    log_level: str = "INFO"
    
    # Database (for latent_item_mappings lookup)
    database_url: str = "postgresql://postgres:postgres@db:5432/ecommerce"
    
    # Redis (optional cache)
    redis_enabled: bool = False
    redis_url: Optional[str] = "redis://redis:6379/0"
    redis_ttl_seconds: int = 3600  # 1 hour default
    
    # ML Artifacts
    artifacts_path: str = "/artifacts"  # Mounted from notebooks/artifacts/
    model_version: str = "latest"  # Model version subdirectory
    
    # Recommendation Parameters
    candidate_pool_size: int = 100  # Initial candidates before ranking
    max_recommendations: int = 50  # Maximum k user can request
    default_recommendations: int = 10  # Default k if not specified
    confidence_threshold: float = 0.5  # Minimum confidence for latent mappings
    
    # Diversity Constraints
    max_items_per_category: int = 3  # Prevent category domination
    
    # Cold Start
    popularity_fallback_size: int = 20  # Popular items for cold start
    
    # Feature Flags
    enable_svd: bool = True
    enable_item_similarity: bool = True
    enable_lightgbm_ranking: bool = True
    
    class Config:
        env_file = ".env"
        case_sensitive = False


# Global settings instance
settings = Settings()


def get_model_path(filename: str) -> Path:
    """
    Resolve versioned model path with backward compatibility.
    
    Args:
        filename: Model filename (e.g., 'svd_model.pkl')
    
    Returns:
        Path to model file
    
    Resolution order:
    1. /artifacts/models/{model_version}/{filename}
    2. /artifacts/models/{filename} (legacy fallback)
    """
    # Try versioned path first
    versioned_path = Path(settings.artifacts_path) / "models" / settings.model_version / filename
    if versioned_path.exists():
        return versioned_path
    
    # Fallback to legacy path
    legacy_path = Path(settings.artifacts_path) / "models" / filename
    return legacy_path
