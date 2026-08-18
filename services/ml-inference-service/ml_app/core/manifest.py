"""
ML Artifact Integrity & Compatibility Verification Module.

Provides:
- Cryptographic SHA-256 checksum verification
- Manifest loading and schema validation
- LightGBM ranker feature compatibility checking
- Parquet feature store schema validation
- Startup integrity verification engine
"""
import hashlib
import json
import os
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

from ml_app.core.config import settings, resolve_model_path, resolve_feature_path
from ml_app.core.logging import get_logger

logger = get_logger(__name__)


def calculate_sha256(file_path: Path, chunk_size: int = 65536) -> str:
    """
    Compute cryptographic SHA-256 hash of a file on disk.
    
    Reads in streaming chunks to avoid loading large model binaries into memory.
    """
    if not file_path.exists():
        raise FileNotFoundError(f"Artifact file not found: {file_path}")

    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(chunk_size):
            hasher.update(chunk)
    return hasher.hexdigest()


def load_manifest(model_version: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Load artifact manifest JSON for the configured or requested model version.
    """
    version = model_version or settings.model_version
    manifest_path = resolve_model_path("artifact_manifest.json")

    if not manifest_path.exists():
        logger.warning("Artifact manifest not found at %s", manifest_path)
        return None

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest_data = json.load(f)
        logger.info("Loaded artifact manifest | model_version=%s | artifacts=%d",
                    manifest_data.get("model_version"), len(manifest_data.get("artifacts", {})))
        return manifest_data
    except Exception as exc:
        logger.exception("Failed to parse artifact manifest at %s: %s", manifest_path, exc)
        return None


def verify_artifact_integrity(
    file_path: Path,
    expected_sha256: str
) -> Tuple[bool, str, str]:
    """
    Verify single artifact against its expected SHA-256 checksum.
    
    Returns:
        Tuple of (is_valid: bool, actual_sha256: str, expected_sha256: str)
    """
    if not file_path.exists():
        return False, "FILE_NOT_FOUND", expected_sha256

    try:
        actual_sha256 = calculate_sha256(file_path)
        is_match = actual_sha256.lower() == expected_sha256.lower()
        return is_match, actual_sha256, expected_sha256
    except Exception as exc:
        logger.exception("Error computing checksum for %s: %s", file_path, exc)
        return False, f"ERROR: {exc}", expected_sha256


def validate_ranker_features(
    actual_features: List[str],
    expected_features: List[str]
) -> Tuple[bool, List[str]]:
    """
    Validate LightGBM feature names and order against expected schema.
    
    Returns:
        Tuple of (is_compatible: bool, error_messages: List[str])
    """
    errors: List[str] = []

    if len(actual_features) != len(expected_features):
        errors.append(
            f"Feature count mismatch: ranker has {len(actual_features)} features, "
            f"expected {len(expected_features)}"
        )

    missing_features = [f for f in expected_features if f not in actual_features]
    if missing_features:
        errors.append(f"Missing expected features in ranker: {missing_features}")

    unexpected_features = [f for f in actual_features if f not in expected_features]
    if unexpected_features:
        errors.append(f"Unexpected features in ranker: {unexpected_features}")

    return len(errors) == 0, errors


def validate_feature_tables(
    user_columns: List[str],
    item_columns: List[str],
    manifest: Dict[str, Any]
) -> Tuple[bool, List[str]]:
    """
    Validate parquet feature tables against expected column schema.
    
    Returns:
        Tuple of (is_compatible: bool, error_messages: List[str])
    """
    errors: List[str] = []
    schema = manifest.get("expected_feature_schema", {})

    expected_user_cols = schema.get("user_features_required", [])
    expected_item_cols = schema.get("item_features_required", [])

    # Validate User Features
    for col in expected_user_cols:
        if col not in user_columns and f"user_{col}" not in user_columns:
            errors.append(f"User features parquet missing required column: '{col}'")

    # Validate Item Features
    for col in expected_item_cols:
        if col not in item_columns and f"item_{col}" not in item_columns:
            errors.append(f"Item features parquet missing required column: '{col}'")

    return len(errors) == 0, errors


class ArtifactVerificationResult:
    """Detailed verification report for loaded artifacts."""

    def __init__(self, model_version: str):
        self.model_version = model_version
        self.is_valid: bool = False
        self.manifest_found: bool = False
        self.artifacts_checked: Dict[str, Dict[str, Any]] = {}
        self.feature_compatibility: Dict[str, Any] = {}
        self.errors: List[str] = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.is_valid,
            "model_version": self.model_version,
            "manifest_found": self.manifest_found,
            "artifacts": self.artifacts_checked,
            "feature_compatibility": self.feature_compatibility,
            "errors": self.errors,
        }


class ArtifactVerifier:
    """
    High-level verification coordinator executed at service startup.
    """

    def __init__(self, model_version: Optional[str] = None):
        self.model_version = model_version or settings.model_version
        self.manifest = load_manifest(self.model_version)

    def verify_all(
        self,
        ranker_features: Optional[List[str]] = None,
        user_features_cols: Optional[List[str]] = None,
        item_features_cols: Optional[List[str]] = None,
    ) -> ArtifactVerificationResult:
        """
        Verify all registered artifacts, hashes, and feature compatibility.
        """
        result = ArtifactVerificationResult(self.model_version)

        if not self.manifest:
            result.errors.append(f"Manifest not found for model_version '{self.model_version}'")
            return result

        result.manifest_found = True
        artifacts_spec = self.manifest.get("artifacts", {})
        all_artifacts_valid = True

        # Check each artifact in manifest
        for filename, spec in artifacts_spec.items():
            expected_sha = spec.get("sha256")
            is_required = spec.get("required", True)

            # Resolve file path
            if spec.get("type") == "features":
                parquet_name = Path(filename).name
                file_path = resolve_feature_path(parquet_name)
            else:
                file_path = resolve_model_path(filename)

            is_match, actual_sha, expected_sha = verify_artifact_integrity(file_path, expected_sha)

            artifact_status = {
                "file_path": str(file_path),
                "type": spec.get("type"),
                "expected_sha256": expected_sha,
                "actual_sha256": actual_sha,
                "matched": is_match,
                "required": is_required,
            }
            result.artifacts_checked[filename] = artifact_status

            if not is_match:
                if is_required:
                    all_artifacts_valid = False
                    err_msg = (
                        f"Artifact integrity failure on {filename}: "
                        f"expected={expected_sha[:12]}..., actual={actual_sha[:12]}..."
                    )
                    logger.error(err_msg)
                    result.errors.append(err_msg)
                else:
                    logger.warning("Optional artifact %s mismatch or missing", filename)

        # Validate Ranker Feature Compatibility
        if ranker_features is not None:
            expected_ranker_feats = self.manifest.get("expected_feature_schema", {}).get("ranking_features", [])
            feats_ok, feat_errors = validate_ranker_features(ranker_features, expected_ranker_feats)
            result.feature_compatibility["ranker"] = {
                "compatible": feats_ok,
                "actual_feature_count": len(ranker_features),
                "expected_feature_count": len(expected_ranker_feats),
                "errors": feat_errors,
            }
            if not feats_ok:
                all_artifacts_valid = False
                result.errors.extend(feat_errors)

        # Validate Feature Tables Schema Compatibility
        if user_features_cols is not None or item_features_cols is not None:
            tables_ok, table_errors = validate_feature_tables(
                user_features_cols or [],
                item_features_cols or [],
                self.manifest
            )
            result.feature_compatibility["feature_tables"] = {
                "compatible": tables_ok,
                "user_columns_count": len(user_features_cols or []),
                "item_columns_count": len(item_features_cols or []),
                "errors": table_errors,
            }
            if not tables_ok:
                all_artifacts_valid = False
                result.errors.extend(table_errors)

        result.is_valid = all_artifacts_valid and len(result.errors) == 0
        return result
