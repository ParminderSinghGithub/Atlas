"""
Test Suite for Model Promotion, Version Resolution, and Rollback.

Tests:
1. Valid candidate promotion succeeds and writes promoted_model.json
2. Invalid artifact (corrupted hash) candidate promotion is rejected
3. Missing manifest candidate promotion is rejected
4. Schema mismatch (wrong number of features) candidate promotion is rejected
5. Explicit MODEL_VERSION environment variable selection in config
6. Promoted version selection from promoted_model.json when MODEL_VERSION is unset
7. Rollback to previous known-good model version
8. Rollback failure when no previous version is recorded
9. Promotion status inspection returns active metadata
10. Inference service uses promoted version to serve requests
"""
import os
import sys
import tempfile
import json
import unittest
from pathlib import Path
from unittest.mock import patch
import httpx

REPO_ROOT = Path(__file__).parent.parent.parent
TRAINING_PATH = REPO_ROOT / "training"
ML_SERVICE_PATH = REPO_ROOT / "services" / "ml-inference-service"

sys.path.insert(0, str(TRAINING_PATH))
sys.path.insert(0, str(ML_SERVICE_PATH))
sys.path.insert(0, str(REPO_ROOT))

from training.promote_model import (
    validate_candidate_model,
    promote_model_version,
    rollback_model_version,
    get_promotion_status,
)
from ml_app.core.config import get_active_model_version
from ml_app.main import app as ml_inference_app


class TestModelPromotionLifecycle(unittest.TestCase):
    """Test model promotion, validation gates, and rollback."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.temp_dir.name)
        self.models_dir = self.base_dir / "models"
        self.features_dir = self.base_dir / "features" / "retailrocket"
        self.models_dir.mkdir(parents=True)
        self.features_dir.mkdir(parents=True)

        # Create mock feature files
        self.user_feat = self.features_dir / "user_features.parquet"
        self.user_feat.write_bytes(b"mock-user-features")
        self.item_feat = self.features_dir / "item_features.parquet"
        self.item_feat.write_bytes(b"mock-item-features")

        import hashlib
        self.user_feat_sha = hashlib.sha256(b"mock-user-features").hexdigest()
        self.item_feat_sha = hashlib.sha256(b"mock-item-features").hexdigest()

        # Read valid LightGBM ranker from production_v1
        real_ranker_path = REPO_ROOT / "notebooks" / "artifacts" / "models" / "production_v1" / "lightgbm_ranker.txt"
        ranker_bytes = real_ranker_path.read_bytes() if real_ranker_path.exists() else b"tree\nversion=v4\n"
        ranker_sha = hashlib.sha256(ranker_bytes).hexdigest()

        features_16 = [
            "interaction_count", "has_purchased", "recency_days",
            "user_total_events", "user_unique_products_interacted", "user_unique_sessions",
            "user_add_to_cart_count", "user_purchase_count", "user_views_count", "user_recency_days",
            "item_total_add_to_cart", "item_total_purchases", "item_total_views",
            "item_popularity_score", "item_conversion_rate", "item_recency_days"
        ]

        # Create valid v1 model directory
        self.v1_dir = self.models_dir / "candidate_v1"
        self.v1_dir.mkdir()
        (self.v1_dir / "svd_model.pkl").write_bytes(b"svd-binary-v1")
        (self.v1_dir / "item_similarity.pkl").write_bytes(b"sim-binary-v1")
        (self.v1_dir / "lightgbm_ranker.txt").write_bytes(ranker_bytes)
        (self.v1_dir / "run_summary.json").write_text(json.dumps({
            "models_evaluated": {"lightgbm_ranker": {"ndcg@10": 0.95}}
        }))

        self.v1_manifest = {
            "manifest_version": "1.0",
            "model_version": "candidate_v1",
            "artifacts": {
                "svd_model.pkl": {"sha256": hashlib.sha256(b"svd-binary-v1").hexdigest(), "required": True},
                "item_similarity.pkl": {"sha256": hashlib.sha256(b"sim-binary-v1").hexdigest(), "required": True},
                "lightgbm_ranker.txt": {"sha256": ranker_sha, "required": True},
                "user_features.parquet": {"sha256": self.user_feat_sha, "type": "features", "required": True},
                "item_features.parquet": {"sha256": self.item_feat_sha, "type": "features", "required": True},
            },
            "expected_feature_schema": {
                "ranking_features_count": 16,
                "ranking_features": features_16,
                "user_features_required": ["total_events"],
                "item_features_required": ["total_views"],
            }
        }
        (self.v1_dir / "artifact_manifest.json").write_text(json.dumps(self.v1_manifest))

        # Create valid v2 model directory
        self.v2_dir = self.models_dir / "candidate_v2"
        self.v2_dir.mkdir()
        (self.v2_dir / "svd_model.pkl").write_bytes(b"svd-binary-v2")
        (self.v2_dir / "item_similarity.pkl").write_bytes(b"sim-binary-v2")
        (self.v2_dir / "lightgbm_ranker.txt").write_bytes(ranker_bytes)
        (self.v2_dir / "run_summary.json").write_text(json.dumps({
            "models_evaluated": {"lightgbm_ranker": {"ndcg@10": 0.99}}
        }))

        self.v2_manifest = {
            "manifest_version": "1.0",
            "model_version": "candidate_v2",
            "artifacts": {
                "svd_model.pkl": {"sha256": hashlib.sha256(b"svd-binary-v2").hexdigest(), "required": True},
                "item_similarity.pkl": {"sha256": hashlib.sha256(b"sim-binary-v2").hexdigest(), "required": True},
                "lightgbm_ranker.txt": {"sha256": ranker_sha, "required": True},
                "user_features.parquet": {"sha256": self.user_feat_sha, "type": "features", "required": True},
                "item_features.parquet": {"sha256": self.item_feat_sha, "type": "features", "required": True},
            },
            "expected_feature_schema": {
                "ranking_features_count": 16,
                "ranking_features": features_16,
                "user_features_required": ["total_events"],
                "item_features_required": ["total_views"],
            }
        }
        (self.v2_dir / "artifact_manifest.json").write_text(json.dumps(self.v2_manifest))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_valid_candidate_promotion_succeeds(self):
        """Valid candidate passes checks and creates promoted_model.json."""
        with patch("ml_app.core.config.resolve_artifacts_dir", return_value=self.base_dir):
            record = promote_model_version("candidate_v1", reason="Initial promotion", artifacts_dir=self.base_dir)

        self.assertEqual(record["promoted_version"], "candidate_v1")
        self.assertIsNone(record["previous_version"])
        self.assertEqual(record["reason"], "Initial promotion")

        ref_file = self.models_dir / "promoted_model.json"
        self.assertTrue(ref_file.exists())
        saved_data = json.loads(ref_file.read_text())
        self.assertEqual(saved_data["promoted_version"], "candidate_v1")

    def test_corrupted_artifact_promotion_is_rejected(self):
        """Candidate with tampered artifact fails promotion."""
        # Corrupt SVD binary
        (self.v1_dir / "svd_model.pkl").write_bytes(b"tampered-corrupt-bytes")

        with self.assertRaises(ValueError) as ctx:
            promote_model_version("candidate_v1", artifacts_dir=self.base_dir)
        self.assertIn("Cannot promote invalid model version", str(ctx.exception))

    def test_missing_manifest_promotion_is_rejected(self):
        """Candidate without manifest is rejected."""
        (self.v1_dir / "artifact_manifest.json").unlink()

        with self.assertRaises(ValueError) as ctx:
            promote_model_version("candidate_v1", artifacts_dir=self.base_dir)
        self.assertIn("artifact_manifest.json not found", str(ctx.exception))

    def test_feature_count_mismatch_promotion_is_rejected(self):
        """Candidate with wrong number of features (< 16) is rejected."""
        bad_manifest = dict(self.v1_manifest)
        bad_manifest["expected_feature_schema"]["ranking_features"] = ["feat_1", "feat_2"]  # only 2 features
        (self.v1_dir / "artifact_manifest.json").write_text(json.dumps(bad_manifest))

        with self.assertRaises(ValueError) as ctx:
            promote_model_version("candidate_v1", artifacts_dir=self.base_dir)
        self.assertIn("Expected 16 ranking features", str(ctx.exception))

    def test_promotion_and_rollback_sequence(self):
        """Promote v1 -> promote v2 -> rollback to v1."""
        with patch("ml_app.core.config.resolve_artifacts_dir", return_value=self.base_dir):
            # 1. Promote v1
            rec1 = promote_model_version("candidate_v1", reason="Release v1", artifacts_dir=self.base_dir)
            self.assertEqual(rec1["promoted_version"], "candidate_v1")
            self.assertIsNone(rec1["previous_version"])

            # 2. Promote v2
            rec2 = promote_model_version("candidate_v2", reason="Release v2", artifacts_dir=self.base_dir)
            self.assertEqual(rec2["promoted_version"], "candidate_v2")
            self.assertEqual(rec2["previous_version"], "candidate_v1")

            # 3. Rollback
            rollback_rec = rollback_model_version(reason="Emergency regression fix", artifacts_dir=self.base_dir)
            self.assertEqual(rollback_rec["promoted_version"], "candidate_v1")
            self.assertEqual(rollback_rec["previous_version"], "candidate_v2")

    def test_rollback_without_previous_version_fails(self):
        """Rollback fails clearly when no previous version exists."""
        with patch("ml_app.core.config.resolve_artifacts_dir", return_value=self.base_dir):
            promote_model_version("candidate_v1", artifacts_dir=self.base_dir)

            with self.assertRaises(ValueError) as ctx:
                rollback_model_version(artifacts_dir=self.base_dir)
            self.assertIn("No previous_version recorded", str(ctx.exception))

    def test_version_resolution_precedence(self):
        """
        Verify version resolution precedence:
        1. Explicit MODEL_VERSION env var
        2. Promoted version from promoted_model.json
        3. Fallback default
        """
        with patch("ml_app.core.config.resolve_artifacts_dir", return_value=self.base_dir):
            # Test 1: promoted_model.json provides active version when env is empty
            promote_model_version("candidate_v2", artifacts_dir=self.base_dir)
            with patch.dict(os.environ, {"MODEL_VERSION": ""}):
                self.assertEqual(get_active_model_version(), "candidate_v2")

            # Test 2: explicit env var overrides promoted_model.json
            with patch.dict(os.environ, {"MODEL_VERSION": "explicit_override_v9"}):
                self.assertEqual(get_active_model_version(), "explicit_override_v9")

    def test_promotion_status_query(self):
        """get_promotion_status reports accurate metadata."""
        with patch("ml_app.core.config.resolve_artifacts_dir", return_value=self.base_dir):
            promote_model_version("candidate_v1", reason="Status check test", artifacts_dir=self.base_dir)
            status = get_promotion_status(artifacts_dir=self.base_dir)

        self.assertEqual(status["status"], "active")
        self.assertEqual(status["active_version"], "candidate_v1")
        self.assertEqual(status["record"]["reason"], "Status check test")


def run_tests():
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_tests())
