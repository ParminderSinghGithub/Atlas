"""
Atlas Recommendation System - Training Pipeline

This package contains scripts for end-to-end model retraining without notebooks.
Notebooks remain fully runnable and are preserved as ML-first artifacts.

Pipeline Steps:
1. ingest_events.py - Load and merge event data
2. build_features.py - Compute features using shared modules
3. train_candidates.py - Train SVD, similarity, popularity models
4. train_ranker.py - Train LightGBM ranker
5. evaluate_and_export.py - Validate metrics and export artifacts
6. run_pipeline.py - Orchestrate all steps

Phase 4.2 - Scripted Training Pipeline
"""

__version__ = "1.0.0"
