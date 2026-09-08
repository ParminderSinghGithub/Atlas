"""
Artifact Downloader for Atlas ML Inference Service.

Handles retrieval of pre-trained model and feature artifacts from a private
Hugging Face model repository when running in containerized cloud environments
(e.g., Railway).
"""
import os
from pathlib import Path
from typing import Optional

from ml_app.core.config import settings, resolve_artifacts_dir, get_active_model_version
from ml_app.core.logging import get_logger

logger = get_logger(__name__)


def are_production_artifacts_present() -> bool:
    """
    Check if the minimum set of production online artifacts exist on local disk.
    """
    base_dir = resolve_artifacts_dir()
    if not base_dir.exists():
        return False

    active_version = get_active_model_version()

    # Core required production files
    required_paths = [
        base_dir / "models" / active_version / "item_similarity.pkl",
        base_dir / "models" / active_version / "lightgbm_ranker.txt",
        base_dir / "features" / "retailrocket" / "user_features.parquet",
        base_dir / "features" / "retailrocket" / "item_features.parquet",
    ]

    for p in required_paths:
        if not p.exists():
            return False

    return True


def ensure_artifacts_available() -> bool:
    """
    Ensure all necessary ML model and feature artifacts are available locally.
    
    1. If production artifacts already exist, skips download.
    2. If missing and HF_MODEL_REPO is configured, downloads from Hugging Face.
    3. Guarantees HF_TOKEN is never logged or exposed.
    """
    if are_production_artifacts_present():
        logger.info(
            "Production ML artifacts verified present in '%s'; skipping download.",
            resolve_artifacts_dir(),
        )
        return True

    repo_id = settings.hf_model_repo or os.getenv("HF_MODEL_REPO")
    token = settings.hf_token or os.getenv("HF_TOKEN")
    revision = settings.hf_revision or os.getenv("HF_REVISION", "main")

    if not repo_id:
        logger.warning(
            "Production ML artifacts missing in '%s' and HF_MODEL_REPO not set; "
            "continuing with local fallback paths.",
            resolve_artifacts_dir(),
        )
        return False

    if not settings.auto_download_artifacts:
        logger.info("auto_download_artifacts is disabled; skipping HF download.")
        return False

    target_dir = Path(settings.artifacts_path)
    target_dir.mkdir(parents=True, exist_ok=True)

    logger.info(
        "Downloading model artifacts from Hugging Face repository '%s' (revision: %s) to '%s'...",
        repo_id,
        revision,
        target_dir,
    )

    try:
        from huggingface_hub import snapshot_download

        downloaded_dir = snapshot_download(
            repo_id=repo_id,
            repo_type="model",
            local_dir=str(target_dir),
            token=token,
            revision=revision,
        )

        logger.info(
            "Successfully acquired model artifacts from Hugging Face to '%s'.",
            downloaded_dir,
        )
        return True

    except Exception as exc:
        # Never log token or sensitive credentials in exception message
        safe_msg = str(exc)
        if token and token in safe_msg:
            safe_msg = safe_msg.replace(token, "[REDACTED_HF_TOKEN]")

        logger.error(
            "Failed to download model artifacts from Hugging Face repo '%s': %s",
            repo_id,
            safe_msg,
        )
        return False
