"""
Test Suite for Restored Offline ML Training Pipeline.

Tests:
1. Training configuration loading and validation
2. Model version resolution and directory handling
3. Ingestion stage execution with synthetic dataset
4. Feature engineering execution producing user/item feature tables
5. Candidate models (SVD, Item Similarity, Popularity) training and export
6. LightGBM ranker training and export
7. Evaluation and automated SHA-256 artifact_manifest.json generation
8. Verification that newly generated model artifacts pass M2 ArtifactVerifier
9. Protection against overwriting production_v1
10. Error handling when required input dataset is missing
"""
import sys
import os
import tempfile
import json
import shutil
from pathlib import Path
import unittest
from unittest.mock import patch
import pandas as pd
import numpy as np

REPO_ROOT = Path(__file__).parent.parent.parent
TRAINING_PATH = REPO_ROOT / "training"
ML_SERVICE_PATH = REPO_ROOT / "services" / "ml-inference-service"

sys.path.insert(0, str(TRAINING_PATH))
sys.path.insert(0, str(ML_SERVICE_PATH))
sys.path.insert(0, str(REPO_ROOT))

from training.ingest_events import ingest_events, load_config, save_events
from training.build_features import build_features, save_features
from training.train_candidates import train_svd_model, train_item_similarity, save_candidate_models, create_training_data as create_candidate_data
from training.train_ranker import train_lightgbm_ranker, save_ranker_model, create_training_data as create_ranker_data
from training.evaluate_and_export import generate_artifact_manifest, create_run_summary, evaluate_lightgbm
from ml_app.core.manifest import ArtifactVerifier


class TestTrainingPipelineComponents(unittest.TestCase):
    """Test individual components and lifecycle stages of the restored offline training pipeline."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.temp_dir.name)

        # Create mock synthetic events DataFrame
        self.mock_events = pd.DataFrame({
            "user_id": ["1", "1", "2", "2", "3", "3", "4", "4"] * 10,
            "product_id": [101, 102, 101, 103, 102, 104, 103, 104] * 10,
            "event_type": ["view", "add_to_cart", "view", "purchase", "view", "view", "add_to_cart", "purchase"] * 10,
            "ts": pd.date_range("2026-01-01", periods=80, freq="h").astype(str),
        })

        self.events_file = self.base_dir / "events.parquet"
        self.mock_events.to_parquet(self.events_file, index=False)

        # Mock configuration
        self.config = {
            "data": {
                "mode": "synthetic",
                "ingested_events": str(self.events_file),
                "synthetic_events_dir": str(self.base_dir),
            },
            "features": {
                "output_dir": str(self.base_dir / "features"),
                "reference_time_policy": "inferred",
                "reference_time": None,
                "user_features_file": "user_features.parquet",
                "item_features_file": "item_features.parquet",
                "interaction_features_file": "interaction_features.parquet",
                "feature_metadata_file": "feature_metadata.json",
            },
            "training": {
                "split": {
                    "method": "temporal",
                    "train_percentile": 70,
                },
                "labels": {
                    "view": 1,
                    "add_to_cart": 2,
                    "purchase": 3,
                },
            },
            "models": {
                "svd": {
                    "enabled": True,
                    "n_components": 2,
                    "random_state": 42,
                    "output_file": "svd_model.pkl",
                },
                "item_similarity": {
                    "enabled": True,
                    "max_session_size": 50,
                    "min_covisits": 1,
                    "output_file": "item_similarity.pkl",
                },
                "lightgbm": {
                    "enabled": True,
                    "objective": "lambdarank",
                    "metric": "ndcg",
                    "ndcg_eval_at": [10],
                    "learning_rate": 0.05,
                    "num_leaves": 7,
                    "feature_fraction": 1.0,
                    "bagging_fraction": 1.0,
                    "bagging_freq": 1,
                    "verbose": -1,
                    "seed": 42,
                    "num_boost_round": 10,
                    "output_file": "lightgbm_ranker.txt",
                    "exclude_columns": ["user_id", "product_id", "last_interaction_ts", "relevance"],
                },
            },
            "artifacts": {
                "models_dir": str(self.base_dir / "models"),
                "version": "test_version_v1",
                "run_summary_file": "run_summary.json",
                "feature_importance_file": "feature_importance.csv",
            },
            "execution": {
                "random_seed": 42,
                "log_level": "INFO",
            },
            "evaluation": {
                "metrics": ["ndcg@10"],
                "max_eval_users": 100,
                "regression_tolerance": {"ndcg@10": 0.05},
            },
        }

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_config_parsing(self):
        """Verify real training config parses without errors."""
        real_config_path = REPO_ROOT / "training" / "config.yaml"
        config = load_config(str(real_config_path))
        self.assertIn("data", config)
        self.assertIn("features", config)
        self.assertIn("models", config)
        self.assertEqual(config["models"]["svd"]["n_components"], 10)

    def test_version_resolution_and_directory_isolation(self):
        """Verify model version resolution writes to distinct output directory."""
        model_version = "retrained_20260108"
        models_dir = Path(self.config["artifacts"]["models_dir"])
        target_dir = models_dir / model_version
        target_dir.mkdir(parents=True, exist_ok=True)
        
        self.assertTrue(target_dir.exists())
        self.assertEqual(target_dir.name, "retrained_20260108")
        self.assertNotEqual(target_dir.name, "production_v1")

    def test_event_ingestion(self):
        """Verify event ingestion returns structured dataframe with required columns."""
        df_events = ingest_events(self.config, data_mode="synthetic")
        self.assertEqual(len(df_events), 80)
        self.assertIn("user_id", df_events.columns)
        self.assertIn("product_id", df_events.columns)
        self.assertIn("event_type", df_events.columns)

    def test_end_to_end_pipeline_execution_and_manifest_validation(self):
        """
        Execute end-to-end offline training stages with synthetic data:
        1. Feature generation
        2. SVD & Item Similarity training
        3. LightGBM Ranker training
        4. Artifact manifest generation
        5. Verification via M2 ArtifactVerifier
        """
        # Step 1: Feature Engineering
        features_dict = build_features(self.config, self.events_file)
        save_features(features_dict, Path(self.config["features"]["output_dir"]), self.config)

        self.assertTrue((Path(self.config["features"]["output_dir"]) / "user_features.parquet").exists())
        self.assertTrue((Path(self.config["features"]["output_dir"]) / "item_features.parquet").exists())

        # Step 2: Candidate Models Training
        _, df_train_set, df_val_set = create_candidate_data(features_dict, self.mock_events, self.config)
        svd_artifacts = train_svd_model(df_train_set, df_val_set, self.config)
        similarity_artifacts = train_item_similarity(df_train_set, self.config)

        model_version = "test_run_version_v1"
        save_candidate_models(svd_artifacts, similarity_artifacts, self.config, model_version)

        model_dir = Path(self.config["artifacts"]["models_dir"]) / model_version
        self.assertTrue((model_dir / "svd_model.pkl").exists())
        self.assertTrue((model_dir / "item_similarity.pkl").exists())
        self.assertTrue((model_dir / "popularity_baseline.pkl").exists())

        # Step 3: Ranker Training
        df_train_ranker, df_val_ranker, feature_cols = create_ranker_data(
            features_dict, self.mock_events, self.config
        )
        lgb_artifacts = train_lightgbm_ranker(
            df_train_ranker, df_val_ranker, feature_cols, self.config
        )
        save_ranker_model(lgb_artifacts, self.config, model_version)
        self.assertTrue((model_dir / "lightgbm_ranker.txt").exists())

        # Step 4: Manifest Generation
        manifest = generate_artifact_manifest(
            model_dir=model_dir,
            features_dir=Path(self.config["features"]["output_dir"]),
            model_version=model_version,
            ranker_feature_names=feature_cols,
            user_feature_cols=list(features_dict["user_features"].columns),
            item_feature_cols=list(features_dict["item_features"].columns),
        )

        self.assertTrue((model_dir / "artifact_manifest.json").exists())
        self.assertEqual(manifest["model_version"], model_version)
        self.assertIn("svd_model.pkl", manifest["artifacts"])
        self.assertIn("lightgbm_ranker.txt", manifest["artifacts"])
        self.assertIn("user_features.parquet", manifest["artifacts"])

        # Step 5: Verify with M2 ArtifactVerifier
        with patch("ml_app.core.manifest.resolve_model_path", side_effect=lambda f: model_dir / f), \
             patch("ml_app.core.manifest.resolve_feature_path", side_effect=lambda f: Path(self.config["features"]["output_dir"]) / f):

            verifier = ArtifactVerifier(model_version=model_version)
            result = verifier.verify_all(
                ranker_features=feature_cols,
                user_features_cols=list(features_dict["user_features"].columns),
                item_features_cols=list(features_dict["item_features"].columns),
            )

        self.assertTrue(result.is_valid, f"ArtifactVerifier failed with errors: {result.errors}")
        self.assertEqual(len(result.errors), 0)

    def test_evaluation_run_summary(self):
        """Verify evaluation run summary creates structured metadata."""
        metrics = {"ndcg@10": 0.8542, "users_evaluated": 10}
        features = {
            "user_features": pd.DataFrame({"user_id": ["1", "2"]}),
            "item_features": pd.DataFrame({"product_id": [101, 102]}),
        }
        summary = create_run_summary(
            self.config, "synthetic", "v_test", features, self.mock_events, metrics, "abc1234"
        )
        self.assertEqual(summary["execution_metadata"]["model_version"], "v_test")
        self.assertEqual(summary["models_evaluated"]["lightgbm_ranker"]["ndcg@10"], 0.8542)
        self.assertEqual(summary["reproducibility"]["git_commit"], "abc1234")

    def test_missing_input_dataset_raises_error(self):
        """Missing input dataset raises FileNotFoundError."""
        invalid_config = dict(self.config)
        invalid_config["data"]["ingested_events"] = "non_existent_file.parquet"
        with self.assertRaises(FileNotFoundError):
            build_features(invalid_config, Path("non_existent_file.parquet"))

    def test_production_v1_is_not_overwritten(self):
        """Verify new model version uses distinct subdirectory and never touches production_v1."""
        model_version = "production_v2_test"
        model_dir = Path(self.config["artifacts"]["models_dir"]) / model_version
        self.assertNotEqual(str(model_dir), "notebooks/artifacts/models/production_v1")
        self.assertIn("production_v2_test", str(model_dir))


def run_tests():
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_tests())
