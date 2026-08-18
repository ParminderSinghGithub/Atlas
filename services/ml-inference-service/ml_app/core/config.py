"""
Configuration for External ML Inference Service.
"""
import os
from pathlib import Path
from typing import Optional

try:
    from pydantic_settings import BaseSettings
except ImportError:
    try:
        from pydantic.v1 import BaseSettings
    except ImportError:
        try:
            from pydantic import BaseSettings
        except ImportError:
            class BaseSettings:
                def __init__(self, **kwargs):
                    for k, v in kwargs.items():
                        setattr(self, k, v)


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Service details
    service_name: str = "atlas-ml-inference-service"
    service_port: int = 8001
    log_level: str = "INFO"

    # Artifact configuration
    artifacts_path: str = "/artifacts"
    model_version: str = "production_v1"

    # ML Inference parameters
    candidate_pool_size: int = 100
    max_candidates: int = 500

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()


def resolve_artifacts_dir() -> Path:
    """
    Resolve base artifacts directory across Docker, local dev, and testing environments.
    """
    configured = Path(settings.artifacts_path)
    if configured.exists():
        return configured

    # Try common local development locations relative to workspace root
    cwd = Path.cwd()
    candidate_paths = [
        cwd / "notebooks" / "artifacts",
        cwd / "training" / "artifacts",
        cwd.parent / "notebooks" / "artifacts",
        cwd.parent.parent / "notebooks" / "artifacts",
        Path(__file__).parent.parent.parent.parent / "notebooks" / "artifacts",
        Path(__file__).parent.parent.parent.parent / "training" / "artifacts",
    ]

    for path in candidate_paths:
        if path.exists():
            return path

    return configured


def resolve_model_path(filename: str) -> Path:
    """
    Resolve specific model artifact path.
    Order:
    1. {artifacts_dir}/models/{model_version}/{filename}
    2. {artifacts_dir}/models/{filename}
    """
    base_dir = resolve_artifacts_dir()

    versioned = base_dir / "models" / settings.model_version / filename
    if versioned.exists():
        return versioned

    flat = base_dir / "models" / filename
    if flat.exists():
        return flat

    return versioned


def resolve_feature_path(feature_filename: str) -> Path:
    """
    Resolve feature parquet path.
    Order:
    1. {artifacts_dir}/features/retailrocket/{feature_filename}
    2. {artifacts_dir}/features/{feature_filename}
    """
    base_dir = resolve_artifacts_dir()

    retailrocket_path = base_dir / "features" / "retailrocket" / feature_filename
    if retailrocket_path.exists():
        return retailrocket_path

    flat_path = base_dir / "features" / feature_filename
    if flat_path.exists():
        return flat_path

    return retailrocket_path
