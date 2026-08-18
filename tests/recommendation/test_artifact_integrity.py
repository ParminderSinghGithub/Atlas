"""
Test Suite for ML Artifact Integrity & Compatibility Verification.

Tests:
1. Valid artifact passes SHA-256 checksum
2. Corrupted artifact fails SHA-256 checksum
3. Missing artifact triggers failure in verification
4. LightGBM feature name/count mismatch triggers validation failure
5. Missing required feature columns in feature store triggers validation failure
6. Valid feature schema passes validation cleanly
7. Metadata endpoint (/metadata) returns complete artifact manifest & schema information
8. Readiness endpoint (/ready) returns HTTP 503 and ready=False when artifact integrity fails
9. Real production_v1 artifacts and manifest load and verify successfully
"""
import sys
import os
import tempfile
import json
from pathlib import Path
import unittest
from unittest.mock import patch, MagicMock
import httpx

REPO_ROOT = Path(__file__).parent.parent.parent
REC_SERVICE_PATH = REPO_ROOT / "services" / "recommendation-service"
ML_SERVICE_PATH = REPO_ROOT / "services" / "ml-inference-service"

sys.path.insert(0, str(ML_SERVICE_PATH))
sys.path.insert(0, str(REC_SERVICE_PATH))

# Ensure mock modules for heavy ML dependencies in test environment
for mod in ["numpy", "lightgbm", "asyncpg", "pandas", "sklearn", "redis", "redis.asyncio"]:
    if mod not in sys.modules:
        try:
            __import__(mod)
        except ImportError:
            sys.modules[mod] = MagicMock()

from ml_app.core.manifest import (
    calculate_sha256,
    verify_artifact_integrity,
    validate_ranker_features,
    validate_feature_tables,
    load_manifest,
    ArtifactVerifier,
)
from ml_app.main import app as ml_inference_app


class TestArtifactChecksums(unittest.TestCase):
    """Test SHA-256 checksum calculation and integrity checking."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_file = Path(self.temp_dir.name) / "test_model.pkl"
        self.test_file.write_bytes(b"deterministic-model-content-for-testing-12345")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_valid_artifact_passes_checksum(self):
        """Valid artifact matches calculated SHA-256."""
        computed_sha = calculate_sha256(self.test_file)
        self.assertTrue(len(computed_sha) == 64)

        is_valid, actual, expected = verify_artifact_integrity(self.test_file, computed_sha)
        self.assertTrue(is_valid)
        self.assertEqual(actual, computed_sha)
        self.assertEqual(expected, computed_sha)

    def test_corrupted_artifact_fails_checksum(self):
        """Corrupted artifact is rejected when SHA-256 differs."""
        original_sha = calculate_sha256(self.test_file)

        # Tamper with file content
        self.test_file.write_bytes(b"tampered-corrupted-model-content-999")

        is_valid, actual, expected = verify_artifact_integrity(self.test_file, original_sha)
        self.assertFalse(is_valid)
        self.assertNotEqual(actual, expected)

    def test_missing_artifact_fails_integrity(self):
        """Non-existent file reports failure safely."""
        missing_path = Path(self.temp_dir.name) / "does_not_exist.pkl"
        is_valid, actual, expected = verify_artifact_integrity(missing_path, "any_sha256")
        self.assertFalse(is_valid)
        self.assertEqual(actual, "FILE_NOT_FOUND")


class TestFeatureSchemaCompatibility(unittest.TestCase):
    """Test LightGBM ranker and feature store schema validation."""

    def setUp(self):
        self.sample_manifest = {
            "model_version": "production_v1",
            "expected_feature_schema": {
                "ranking_features_count": 16,
                "ranking_features": [
                    "interaction_count", "has_purchased", "recency_days",
                    "user_total_events", "user_unique_products_interacted", "user_unique_sessions",
                    "user_add_to_cart_count", "user_purchase_count", "user_views_count", "user_recency_days",
                    "item_total_add_to_cart", "item_total_purchases", "item_total_views",
                    "item_popularity_score", "item_conversion_rate", "item_recency_days"
                ],
                "user_features_required": [
                    "total_events", "unique_products_interacted", "unique_sessions",
                    "add_to_cart_count", "purchase_count", "views_count", "recency_days"
                ],
                "item_features_required": [
                    "total_views", "total_add_to_cart", "total_purchases",
                    "popularity_score", "conversion_rate", "recency_days"
                ]
            }
        }

    def test_valid_ranker_features_pass(self):
        """Exact matching feature list passes ranker validation."""
        expected = self.sample_manifest["expected_feature_schema"]["ranking_features"]
        is_compat, errors = validate_ranker_features(expected, expected)
        self.assertTrue(is_compat)
        self.assertEqual(len(errors), 0)

    def test_ranker_feature_count_mismatch_fails(self):
        """Truncated or extra feature lists fail ranker validation."""
        truncated = ["interaction_count", "has_purchased", "recency_days"]
        expected = self.sample_manifest["expected_feature_schema"]["ranking_features"]
        is_compat, errors = validate_ranker_features(truncated, expected)
        self.assertFalse(is_compat)
        self.assertTrue(any("count mismatch" in e for e in errors))

    def test_ranker_missing_named_feature_fails(self):
        """Wrong feature names fail ranker validation."""
        corrupted = list(self.sample_manifest["expected_feature_schema"]["ranking_features"])
        corrupted[0] = "wrong_feature_name"
        expected = self.sample_manifest["expected_feature_schema"]["ranking_features"]
        is_compat, errors = validate_ranker_features(corrupted, expected)
        self.assertFalse(is_compat)
        self.assertTrue(any("Missing expected features" in e for e in errors))

    def test_valid_feature_tables_pass(self):
        """User and Item feature tables with required columns pass validation."""
        user_cols = ["total_events", "unique_products_interacted", "unique_sessions",
                     "add_to_cart_count", "purchase_count", "views_count", "recency_days"]
        item_cols = ["total_views", "total_add_to_cart", "total_purchases",
                     "popularity_score", "conversion_rate", "recency_days"]

        is_compat, errors = validate_feature_tables(user_cols, item_cols, self.sample_manifest)
        self.assertTrue(is_compat)
        self.assertEqual(len(errors), 0)

    def test_missing_feature_table_column_fails(self):
        """Feature table missing required column fails validation."""
        user_cols = ["total_events", "unique_sessions"]  # missing 5 required columns
        item_cols = ["total_views"]  # missing 5 required columns

        is_compat, errors = validate_feature_tables(user_cols, item_cols, self.sample_manifest)
        self.assertFalse(is_compat)
        self.assertTrue(any("User features parquet missing" in e for e in errors))
        self.assertTrue(any("Item features parquet missing" in e for e in errors))


class TestManifestLoadingAndEndpoints(unittest.IsolatedAsyncioTestCase):
    """Test manifest loading, /ready integrity enforcement, and /metadata."""

    def test_production_manifest_loads_cleanly(self):
        """Ensure real production_v1 manifest exists and parses."""
        manifest = load_manifest("production_v1")
        self.assertIsNotNone(manifest)
        self.assertEqual(manifest["model_version"], "production_v1")
        self.assertIn("svd_model.pkl", manifest["artifacts"])
        self.assertIn("lightgbm_ranker.txt", manifest["artifacts"])

    async def test_metadata_endpoint_returns_integrity_info(self):
        """GET /metadata returns complete artifact status."""
        transport = httpx.ASGITransport(app=ml_inference_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/metadata")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["service_name"], "atlas-ml-inference-service")
            self.assertEqual(data["model_version"], "production_v1")
            self.assertIn("artifacts", data)
            self.assertIn("feature_compatibility", data)

    async def test_ready_endpoint_fails_when_integrity_fails(self):
        """GET /ready returns HTTP 503 if verification failed."""
        from ml_app.core.manifest import ArtifactVerificationResult

        mock_failed_result = ArtifactVerificationResult("production_v1")
        mock_failed_result.is_valid = False
        mock_failed_result.errors = ["Artifact integrity failure on svd_model.pkl: checksum mismatch"]

        with patch.object(ml_inference_app.state, "verification_result", mock_failed_result, create=True):
            transport = httpx.ASGITransport(app=ml_inference_app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/ready")
                self.assertEqual(resp.status_code, 503)
                data = resp.json()
                self.assertFalse(data["ready"])
                self.assertFalse(data["integrity_verified"])
                self.assertTrue(len(data["errors"]) > 0)


def run_tests():
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_tests())
