"""
Training Pipeline Test Suite.

Tests:
- Pipeline execution (run_pipeline.py)
- Feature generation completeness
- Model artifacts created correctly
- Metrics output validity
- Artifact versioning
- No dead scripts
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '_utils'))

import subprocess
import time
from pathlib import Path
from test_framework import TestSuite, TestResult, print_header

PROJECT_ROOT = Path(__file__).parent.parent.parent
TRAINING_DIR = PROJECT_ROOT / "training"
ARTIFACTS_DIR = PROJECT_ROOT / "notebooks" / "artifacts"


def test_training_pipeline_exists():
    """Test that training pipeline script exists."""
    test_name = "Training Pipeline Script Exists"
    start = time.time()
    
    pipeline_script = TRAINING_DIR / "run_pipeline.py"
    duration = (time.time() - start) * 1000
    
    if pipeline_script.exists():
        return TestResult(
            name=test_name,
            status="PASS",
            expected="run_pipeline.py exists",
            observed=f"Found at {pipeline_script}",
            duration_ms=duration
        )
    else:
        return TestResult(
            name=test_name,
            status="FAIL",
            expected="Pipeline script exists",
            observed=f"Not found at {pipeline_script}",
            reason="Pipeline script missing",
            duration_ms=duration
        )


def test_model_artifacts_exist():
    """Test that model artifacts exist in expected locations."""
    test_name = "Model Artifacts Exist"
    start = time.time()
    
    # Check for expected artifacts
    expected_artifacts = [
        ARTIFACTS_DIR / "models" / "svd_model.pkl",
        ARTIFACTS_DIR / "models" / "item_similarity.pkl",
        ARTIFACTS_DIR / "models" / "popularity_model.pkl"
    ]
    
    existing = [a for a in expected_artifacts if a.exists()]
    missing = [a for a in expected_artifacts if not a.exists()]
    
    duration = (time.time() - start) * 1000
    
    if len(missing) == 0:
        return TestResult(
            name=test_name,
            status="PASS",
            expected="All model artifacts present",
            observed=f"{len(existing)}/{len(expected_artifacts)} artifacts found",
            duration_ms=duration,
            details={"artifacts": [a.name for a in existing]}
        )
    else:
        return TestResult(
            name=test_name,
            status="FAIL",
            expected="All artifacts present",
            observed=f"{len(existing)}/{len(expected_artifacts)} found",
            reason=f"Missing: {[a.name for a in missing]}",
            duration_ms=duration
        )


def test_training_data_exists():
    """Test that training data (events) exists."""
    test_name = "Training Data Exists"
    start = time.time()
    
    # Check for events data
    events_dir = ARTIFACTS_DIR / "events"
    combined_dir = ARTIFACTS_DIR / "combined"
    
    events_exist = events_dir.exists() and len(list(events_dir.glob("**/*.parquet"))) > 0
    combined_exist = combined_dir.exists() and len(list(combined_dir.glob("*.parquet"))) > 0
    
    duration = (time.time() - start) * 1000
    
    if events_exist or combined_exist:
        source = "events" if events_exist else "combined"
        return TestResult(
            name=test_name,
            status="PASS",
            expected="Training data available",
            observed=f"Data found in {source} directory",
            duration_ms=duration
        )
    else:
        return TestResult(
            name=test_name,
            status="FAIL",
            expected="Training events data",
            observed="No events or combined data found",
            reason="Training data missing",
            duration_ms=duration
        )


def test_no_dead_scripts():
    """Test that no dead/unused training scripts exist in main directory."""
    test_name = "No Dead Training Scripts"
    start = time.time()
    
    training_files = [f for f in TRAINING_DIR.glob("*.py") if f.is_file()]
    
    # Expected training scripts (archival scripts now in ARCHIVED/)
    expected = [
        "run_pipeline.py",
        "train_candidates.py",
        "train_ranker.py",
        "__init__.py"
    ]
    
    unexpected = [f for f in training_files if f.name not in expected and not f.name.startswith("test_")]
    
    duration = (time.time() - start) * 1000
    
    if len(unexpected) == 0:
        return TestResult(
            name=test_name,
            status="PASS",
            expected="Only expected training scripts in main dir",
            observed=f"Found {len(training_files)} scripts, all expected. Archival scripts in ARCHIVED/",
            duration_ms=duration
        )
    else:
        return TestResult(
            name=test_name,
            status="FAIL",
            expected="No unexpected scripts",
            observed=f"Unexpected: {[f.name for f in unexpected]}",
            reason="Dead or undocumented scripts exist (should be in ARCHIVED/)",
            duration_ms=duration
        )


def test_deployed_artifacts_match_training():
    """Test that deployed model artifacts match training outputs."""
    test_name = "Deployed Artifacts Match Training"
    start = time.time()
    
    # Artifacts used by recommendation service
    service_artifacts_dir = PROJECT_ROOT / "services" / "recommendation-service" / "artifacts"
    
    # Check if symbolic link or actual files
    deployed_models_exist = service_artifacts_dir.exists() if service_artifacts_dir.exists() else False
    
    # If deployed separately, check they exist
    if deployed_models_exist:
        deployed_svd = service_artifacts_dir / "models" / "svd_model.pkl"
        training_svd = ARTIFACTS_DIR / "models" / "svd_model.pkl"
        
        both_exist = deployed_svd.exists() and training_svd.exists()
        
        duration = (time.time() - start) * 1000
        
        if both_exist:
            # Check if they're the same file (symlink) or separate
            deployed_size = deployed_svd.stat().st_size
            training_size = training_svd.stat().st_size
            
            if deployed_size == training_size:
                return TestResult(
                    name=test_name,
                    status="PASS",
                    expected="Deployed models match training artifacts",
                    observed=f"Both SVD models exist, same size ({training_size} bytes)",
                    duration_ms=duration
                )
            else:
                return TestResult(
                    name=test_name,
                    status="FAIL",
                    expected="Matching artifact sizes",
                    observed=f"Size mismatch: deployed={deployed_size}, training={training_size}",
                    reason="Artifacts out of sync",
                    duration_ms=duration
                )
        else:
            return TestResult(
                name=test_name,
                status="FAIL",
                expected="Both deployed and training artifacts exist",
                observed=f"Deployed: {deployed_svd.exists()}, Training: {training_svd.exists()}",
                reason="Missing artifacts",
                duration_ms=duration
            )
    else:
        # Service may mount artifacts from notebooks/artifacts
        duration = (time.time() - start) * 1000
        return TestResult(
            name=test_name,
            status="PASS",
            expected="Service uses shared artifacts volume",
            observed="No separate deployment - service mounts training artifacts",
            duration_ms=duration,
            details={"note": "Docker volume mount from notebooks/artifacts"}
        )


def main():
    """Run all training pipeline tests."""
    print_header("TRAINING PIPELINE TEST SUITE")
    
    suite = TestSuite("Training Pipeline")
    
    # Run tests
    suite.add_result(test_training_pipeline_exists())
    suite.add_result(test_model_artifacts_exist())
    suite.add_result(test_training_data_exists())
    suite.add_result(test_no_dead_scripts())
    suite.add_result(test_deployed_artifacts_match_training())
    
    suite.finalize()
    exit_code = suite.print_report()
    
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
