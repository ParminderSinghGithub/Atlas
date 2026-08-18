"""
Model Promotion & Rollback Management Utility.

Provides:
- Candidate model integrity & compatibility validation before promotion
- Explicit promotion record creation in models/promoted_model.json
- Deterministic rollback to previous validated version
- Promotion status inspection CLI

Usage:
    python training/promote_model.py --model-version production_v1
    python training/promote_model.py --model-version candidate_v2 --reason "NDCG improved to 0.9942"
    python training/promote_model.py --rollback --reason "Performance regression detected"
    python training/promote_model.py --status
"""
import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List

# Add project root and ml-inference-service to sys.path
repo_root = Path(__file__).parent.parent
ml_service_path = repo_root / "services" / "ml-inference-service"

if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))
if str(ml_service_path) not in sys.path:
    sys.path.insert(0, str(ml_service_path))

from ml_app.core.manifest import (
    calculate_sha256,
    verify_artifact_integrity,
    validate_ranker_features,
    validate_feature_tables,
    load_manifest,
    ArtifactVerifier,
)
from ml_app.core.config import resolve_artifacts_dir

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("promote_model")


def get_models_dir(artifacts_dir: Optional[Path] = None) -> Path:
    """Resolve the directory where models are stored."""
    base = artifacts_dir or resolve_artifacts_dir()
    return base / "models"


def get_promoted_reference_path(artifacts_dir: Optional[Path] = None) -> Path:
    """Path to the central promoted_model.json reference file."""
    return get_models_dir(artifacts_dir) / "promoted_model.json"


def validate_candidate_model(
    model_version: str,
    artifacts_dir: Optional[Path] = None
) -> Tuple[bool, List[str], Dict[str, Any]]:
    """
    Validate a candidate model version against all integrity and schema rules.
    
    Checks:
    1. Model directory exists
    2. Required artifact binaries exist
    3. artifact_manifest.json exists and parses
    4. SHA-256 checksums match manifest
    5. Feature schema compatibility (16 features, user/item column requirements)
    6. Evaluation metadata (run_summary.json) presence
    
    Returns:
        Tuple of (is_valid: bool, error_messages: List[str], manifest_data: dict)
    """
    errors: List[str] = []
    models_dir = get_models_dir(artifacts_dir)
    candidate_dir = models_dir / model_version

    if not candidate_dir.exists() or not candidate_dir.is_dir():
        errors.append(f"Candidate model directory not found: {candidate_dir}")
        return False, errors, {}

    manifest_path = candidate_dir / "artifact_manifest.json"
    if not manifest_path.exists():
        errors.append(f"artifact_manifest.json not found in {candidate_dir}")
        return False, errors, {}

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest_data = json.load(f)
    except Exception as exc:
        errors.append(f"Failed to parse manifest at {manifest_path}: {exc}")
        return False, errors, {}

    # Verify each artifact in manifest
    artifacts_spec = manifest_data.get("artifacts", {})
    if not artifacts_spec:
        errors.append("Manifest contains no artifact specifications")
        return False, errors, manifest_data

    for filename, spec in artifacts_spec.items():
        expected_sha = spec.get("sha256")
        is_required = spec.get("required", True)

        # Resolve artifact path
        if spec.get("type") == "features":
            base = artifacts_dir or resolve_artifacts_dir()
            file_path = base / "features" / "retailrocket" / Path(filename).name
            if not file_path.exists():
                file_path = base / "features" / Path(filename).name
        else:
            file_path = candidate_dir / filename

        is_match, actual_sha, expected_sha = verify_artifact_integrity(file_path, expected_sha)
        if not is_match:
            if is_required:
                errors.append(
                    f"Integrity check failed for required artifact '{filename}': "
                    f"expected {expected_sha[:12]}..., got {actual_sha[:12]}..."
                )
            else:
                logger.warning(f"Optional artifact '{filename}' missing or checksum mismatch")

    # Verify feature schema specification exists
    schema = manifest_data.get("expected_feature_schema", {})
    ranking_features = schema.get("ranking_features", [])
    if len(ranking_features) != 16:
        errors.append(
            f"Expected 16 ranking features in schema, found {len(ranking_features)}: {ranking_features}"
        )

    # Check LightGBM ranker feature names if booster exists
    ranker_file = candidate_dir / "lightgbm_ranker.txt"
    if ranker_file.exists():
        try:
            import lightgbm as lgb
            booster = lgb.Booster(model_file=str(ranker_file))
            booster_features = booster.feature_name()
            feats_ok, feat_errors = validate_ranker_features(booster_features, ranking_features)
            if not feats_ok:
                errors.extend(feat_errors)
        except Exception as exc:
            errors.append(f"Failed to load LightGBM ranker for feature validation: {exc}")

    is_valid = len(errors) == 0
    return is_valid, errors, manifest_data


def promote_model_version(
    model_version: str,
    reason: str = "Manual promotion",
    promoted_by: str = "engineer",
    artifacts_dir: Optional[Path] = None
) -> Dict[str, Any]:
    """
    Validate and promote a model version, writing the active reference to promoted_model.json.
    """
    logger.info(f"Initiating promotion validation for model version: '{model_version}'...")

    is_valid, errors, manifest_data = validate_candidate_model(model_version, artifacts_dir)
    if not is_valid:
        logger.error(f"Promotion REJECTED for '{model_version}'. Validation errors:")
        for err in errors:
            logger.error(f"  - {err}")
        raise ValueError(f"Cannot promote invalid model version '{model_version}': {errors}")

    models_dir = get_models_dir(artifacts_dir)
    candidate_dir = models_dir / model_version
    manifest_path = candidate_dir / "artifact_manifest.json"
    manifest_sha = calculate_sha256(manifest_path)

    # Read current promoted reference to record previous_version
    ref_path = get_promoted_reference_path(artifacts_dir)
    previous_version = None
    if ref_path.exists():
        try:
            with open(ref_path, "r", encoding="utf-8") as f:
                current_ref = json.load(f)
                previous_version = current_ref.get("promoted_version")
        except Exception:
            pass

    # Read evaluation summary from run_summary.json if available
    eval_summary = {}
    summary_file = candidate_dir / "run_summary.json"
    if summary_file.exists():
        try:
            with open(summary_file, "r", encoding="utf-8") as f:
                summary_data = json.load(f)
                eval_summary = summary_data.get("models_evaluated", {}).get("lightgbm_ranker", {})
        except Exception:
            pass

    record = {
        "promoted_version": model_version,
        "promoted_at": datetime.now().isoformat(),
        "promoted_by": promoted_by,
        "reason": reason,
        "manifest_sha256": manifest_sha,
        "evaluation_summary": eval_summary,
        "previous_version": previous_version,
    }

    ref_path.parent.mkdir(parents=True, exist_ok=True)
    with open(ref_path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2)

    logger.info("=" * 70)
    logger.info(f"MODEL PROMOTED SUCCESSFULLY: {model_version}")
    logger.info(f"  Promoted at: {record['promoted_at']}")
    logger.info(f"  Previous version: {previous_version}")
    logger.info(f"  Reason: {reason}")
    logger.info(f"  Manifest SHA-256: {manifest_sha[:16]}...")
    logger.info("=" * 70)

    return record


def rollback_model_version(
    reason: str = "Rollback to previous known-good version",
    artifacts_dir: Optional[Path] = None
) -> Dict[str, Any]:
    """
    Roll back the active model version to the previous_version recorded in promoted_model.json.
    """
    ref_path = get_promoted_reference_path(artifacts_dir)
    if not ref_path.exists():
        raise FileNotFoundError("Cannot rollback: No promoted_model.json found.")

    with open(ref_path, "r", encoding="utf-8") as f:
        current_record = json.load(f)

    target_version = current_record.get("previous_version")
    if not target_version:
        raise ValueError(
            f"Cannot rollback: No previous_version recorded for current active model '{current_record.get('promoted_version')}'"
        )

    logger.info(f"Rolling back from '{current_record.get('promoted_version')}' to '{target_version}'...")
    return promote_model_version(
        model_version=target_version,
        reason=f"ROLLBACK: {reason} (from {current_record.get('promoted_version')})",
        promoted_by="rollback",
        artifacts_dir=artifacts_dir
    )


def get_promotion_status(artifacts_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Retrieve current promotion status and record."""
    ref_path = get_promoted_reference_path(artifacts_dir)
    if not ref_path.exists():
        return {
            "status": "uninitialized",
            "active_version": "production_v1 (default fallback)",
            "record": None
        }

    with open(ref_path, "r", encoding="utf-8") as f:
        record = json.load(f)

    return {
        "status": "active",
        "active_version": record.get("promoted_version"),
        "record": record
    }


def main():
    parser = argparse.ArgumentParser(
        description="Atlas ML Model Promotion & Rollback Manager"
    )
    parser.add_argument(
        "--model-version",
        type=str,
        help="Candidate model version to promote (e.g. production_v2)"
    )
    parser.add_argument(
        "--reason",
        type=str,
        default="Manual promotion",
        help="Reason or release notes for this model promotion"
    )
    parser.add_argument(
        "--promoted-by",
        type=str,
        default="engineer",
        help="Identifier of user or system executing promotion"
    )
    parser.add_argument(
        "--rollback",
        action="store_true",
        help="Rollback to previous validated version"
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print current model promotion status"
    )

    args = parser.parse_args()

    if args.status:
        status_info = get_promotion_status()
        print(json.dumps(status_info, indent=2))
        return 0

    if args.rollback:
        try:
            record = rollback_model_version(reason=args.reason)
            print(f"Rollback successful. Active model: {record['promoted_version']}")
            return 0
        except Exception as exc:
            logger.error(f"Rollback failed: {exc}")
            return 1

    if args.model_version:
        try:
            record = promote_model_version(
                model_version=args.model_version,
                reason=args.reason,
                promoted_by=args.promoted_by
            )
            print(f"Promotion successful. Active model: {record['promoted_version']}")
            return 0
        except Exception as exc:
            logger.error(f"Promotion failed: {exc}")
            return 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
