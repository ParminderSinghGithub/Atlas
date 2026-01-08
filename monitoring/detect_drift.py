#!/usr/bin/env python3
"""
Basic Drift Detection for Atlas Recommendation System

Purpose:
    Detect data drift by comparing production feature distributions
    against training baseline statistics.

What is Monitored:
    - Feature mean/variance shifts (user & item features)
    - Category distribution changes
    - Popularity rank shifts

Why Basic:
    - No ML drift detection tools (Evidently AI, NannyML)
    - Simple statistical comparisons (mean, variance, KL divergence)
    - Manual review of drift signals (no auto-alerts)
    - Sufficient for low-traffic platforms

Input:
    - Training baseline: training/artifacts/features/item_features.parquet
    - Production features: services/recommendation-service/artifacts/features/

Output:
    JSON report with drift signals (no alerts, logging only)

Usage:
    python monitoring/detect_drift.py

Why This Matters:
    - Training data: 2014-2015 RetailRocket events
    - Production data: 2026 Amazon catalog
    - Large domain shift is EXPECTED (different products, different era)
    - This script detects UNEXPECTED drift (e.g., feature corruption, category imbalance)
"""

import sys
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Tuple
import warnings

# Suppress pandas warnings
warnings.filterwarnings('ignore')

try:
    import pandas as pd
    import numpy as np
except ImportError:
    print("Error: pandas and numpy required. Install with: pip install pandas numpy", file=sys.stderr)
    sys.exit(1)


def load_training_baseline(artifacts_dir: Path) -> Dict[str, Any]:
    """
    Load training feature statistics as baseline.
    
    Returns:
        Dict with baseline statistics:
        - item_feature_means: Mean of each item feature
        - item_feature_stds: Std deviation of each item feature
        - category_distribution: Category counts
    """
    item_features_path = artifacts_dir / "features" / "item_features.parquet"
    
    if not item_features_path.exists():
        return {
            "error": f"Training baseline not found: {item_features_path}",
            "available": False
        }
    
    try:
        df = pd.read_parquet(item_features_path)
        
        # Extract numeric features only
        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        
        # Compute baseline statistics
        baseline = {
            "available": True,
            "num_items": len(df),
            "feature_means": df[numeric_cols].mean().to_dict(),
            "feature_stds": df[numeric_cols].std().to_dict(),
            "feature_columns": numeric_cols
        }
        
        # Category distribution if available
        if 'category_id' in df.columns:
            baseline["category_distribution"] = df['category_id'].value_counts().to_dict()
        
        return baseline
    
    except Exception as e:
        return {
            "error": f"Failed to load training baseline: {e}",
            "available": False
        }


def compute_drift_metrics(baseline: Dict[str, Any], production: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compute drift signals between baseline and production.
    
    Metrics:
    - Feature mean shift: (prod_mean - baseline_mean) / baseline_std
    - Feature variance ratio: prod_std / baseline_std
    - Category distribution shift (if available)
    
    Returns:
        Drift report with signal strengths
    """
    if not baseline.get("available"):
        return {"error": "Training baseline not available"}
    
    if not production.get("available"):
        return {"error": "Production features not available"}
    
    drift_signals = {
        "feature_shifts": {},
        "variance_ratios": {},
        "category_drift": None
    }
    
    # Feature mean shift
    for feature in baseline.get("feature_columns", []):
        if feature in baseline["feature_means"] and feature in production.get("feature_means", {}):
            baseline_mean = baseline["feature_means"][feature]
            baseline_std = baseline["feature_stds"].get(feature, 1.0)
            prod_mean = production["feature_means"][feature]
            
            # Standardized shift: how many std deviations has the mean moved?
            if baseline_std > 0:
                shift = (prod_mean - baseline_mean) / baseline_std
                drift_signals["feature_shifts"][feature] = round(shift, 3)
    
    # Variance ratio
    for feature in baseline.get("feature_columns", []):
        if feature in baseline["feature_stds"] and feature in production.get("feature_stds", {}):
            baseline_std = baseline["feature_stds"][feature]
            prod_std = production["feature_stds"][feature]
            
            if baseline_std > 0:
                ratio = prod_std / baseline_std
                drift_signals["variance_ratios"][feature] = round(ratio, 3)
    
    # Category distribution shift (simplified)
    if "category_distribution" in baseline and "category_distribution" in production:
        baseline_cats = set(baseline["category_distribution"].keys())
        prod_cats = set(production["category_distribution"].keys())
        
        drift_signals["category_drift"] = {
            "new_categories": list(prod_cats - baseline_cats),
            "missing_categories": list(baseline_cats - prod_cats),
            "overlap": len(baseline_cats & prod_cats)
        }
    
    return drift_signals


def interpret_drift(drift_signals: Dict[str, Any]) -> Dict[str, Any]:
    """
    Interpret drift signals and flag concerning patterns.
    
    Thresholds (conservative for expected domain shift):
    - Feature shift > 3.0 std: Significant drift
    - Variance ratio > 5.0 or < 0.2: Distribution shape changed
    - Category drift: New/missing categories expected (RetailRocket → Amazon)
    """
    interpretations = {
        "significant_shifts": [],
        "variance_changes": [],
        "overall_assessment": "HEALTHY"
    }
    
    # Feature shifts
    for feature, shift in drift_signals.get("feature_shifts", {}).items():
        if abs(shift) > 3.0:
            interpretations["significant_shifts"].append({
                "feature": feature,
                "shift_std": shift,
                "severity": "HIGH" if abs(shift) > 5.0 else "MEDIUM"
            })
    
    # Variance changes
    for feature, ratio in drift_signals.get("variance_ratios", {}).items():
        if ratio > 5.0 or ratio < 0.2:
            interpretations["variance_changes"].append({
                "feature": feature,
                "ratio": ratio,
                "interpretation": "Increased variance" if ratio > 1 else "Decreased variance"
            })
    
    # Overall assessment
    if len(interpretations["significant_shifts"]) > 5:
        interpretations["overall_assessment"] = "DRIFT_DETECTED"
    elif len(interpretations["significant_shifts"]) > 2:
        interpretations["overall_assessment"] = "MONITOR"
    
    return interpretations


def main():
    """
    Run drift detection and output JSON report.
    """
    print("Atlas Drift Detection - Starting...", file=sys.stderr)
    
    # Paths
    project_root = Path(__file__).parent.parent
    training_artifacts = project_root / "training" / "artifacts"
    
    # Load training baseline
    print("Loading training baseline...", file=sys.stderr)
    baseline = load_training_baseline(training_artifacts)
    
    if not baseline.get("available"):
        print(f"Error: {baseline.get('error')}", file=sys.stderr)
        report = {
            "status": "ERROR",
            "message": baseline.get("error"),
            "baseline_available": False
        }
    else:
        print(f"Baseline loaded: {baseline['num_items']} items, {len(baseline['feature_columns'])} features", file=sys.stderr)
        
        # For now, we don't have "production" features distinct from training
        # In a real system, this would compare live feature distributions
        # For demonstration, we'll note this limitation
        
        report = {
            "status": "BASELINE_ONLY",
            "message": "Production feature tracking not yet implemented. This is a demonstration of drift detection structure.",
            "baseline_summary": {
                "num_items": baseline["num_items"],
                "num_features": len(baseline["feature_columns"]),
                "features_tracked": baseline["feature_columns"][:10]  # First 10 features
            },
            "interpretation": {
                "domain_shift_expected": True,
                "reason": "Training on RetailRocket (2014-2015), serving with Amazon catalog (2026)",
                "monitoring_focus": "Look for UNEXPECTED shifts (feature corruption, data pipeline errors)"
            },
            "next_steps": [
                "Collect production feature snapshots periodically",
                "Compare against baseline monthly",
                "Alert on severe drift (>5 std shift)"
            ]
        }
    
    # Add metadata
    report["metadata"] = {
        "generated_at": datetime.utcnow().isoformat(),
        "baseline_path": str(training_artifacts / "features" / "item_features.parquet")
    }
    
    # Output JSON
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
