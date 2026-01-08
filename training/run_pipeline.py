"""
Training Pipeline Orchestrator

Runs all training steps in sequence:
1. Ingest events
2. Build features
3. Train candidate models
4. Train ranker
5. Evaluate and export

Usage:
    python run_pipeline.py --model-version v1
    python run_pipeline.py --config custom_config.yaml --model-version 20260107_120000
    python run_pipeline.py --model-version v1 --dry-run
"""

import argparse
import logging
import sys
from pathlib import Path
from datetime import datetime
import yaml
import subprocess

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_config(config_path: str) -> dict:
    """Load YAML configuration file."""
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    return config


def get_python_executable() -> str:
    """Get the Python executable, preferring venv if available."""
    # Check for venv in training directory
    venv_paths = [
        Path('training/venv/Scripts/python.exe'),  # Windows
        Path('training/venv/bin/python'),  # Unix-like
    ]
    
    for venv_path in venv_paths:
        if venv_path.exists():
            logger.info(f"Using virtual environment: {venv_path}")
            return str(venv_path)
    
    # Fallback to system Python
    logger.info(f"Using system Python: {sys.executable}")
    return sys.executable


def run_step(script_name: str, args: list, dry_run: bool = False) -> int:
    """
    Run a pipeline step.
    
    Args:
        script_name: Name of the script to run
        args: Command-line arguments to pass
        dry_run: If True, only print the command without executing
    
    Returns:
        Exit code (0 = success)
    """
    # Build command
    python_exe = get_python_executable()
    cmd = [python_exe, script_name] + args
    cmd_str = ' '.join(cmd)
    
    logger.info(f"{'[DRY RUN] ' if dry_run else ''}Running: {cmd_str}")
    
    if dry_run:
        return 0
    
    # Execute command
    try:
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=False,
            text=True
        )
        logger.info(f"✓ {script_name} completed successfully")
        return 0
    
    except subprocess.CalledProcessError as e:
        logger.error(f"✗ {script_name} failed with exit code {e.returncode}")
        return e.returncode


def main():
    parser = argparse.ArgumentParser(
        description='Run complete training pipeline'
    )
    parser.add_argument(
        '--config',
        type=str,
        default='training/config.yaml',
        help='Path to configuration file'
    )
    parser.add_argument(
        '--model-version',
        type=str,
        help='Model version for artifact storage (e.g., v1, 20260107_120000). Auto-generated if not provided.'
    )
    parser.add_argument(
        '--data-mode',
        type=str,
        choices=['retailrocket', 'synthetic', 'merged'],
        help='Override data mode from config'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Print commands without executing them'
    )
    parser.add_argument(
        '--skip-ingest',
        action='store_true',
        help='Skip event ingestion (use existing ingested events)'
    )
    parser.add_argument(
        '--skip-features',
        action='store_true',
        help='Skip feature building (use existing features)'
    )
    parser.add_argument(
        '--skip-candidates',
        action='store_true',
        help='Skip candidate model training'
    )
    parser.add_argument(
        '--skip-ranker',
        action='store_true',
        help='Skip ranker training'
    )
    parser.add_argument(
        '--skip-evaluation',
        action='store_true',
        help='Skip evaluation'
    )
    parser.add_argument(
        '--baseline',
        type=str,
        help='Path to baseline run_summary.json for comparison'
    )
    
    args = parser.parse_args()
    
    # Load configuration
    config = load_config(args.config)
    
    # Set log level
    log_level = config.get('execution', {}).get('log_level', 'INFO')
    logger.setLevel(getattr(logging, log_level))
    
    # Auto-generate model version if not provided
    model_version = args.model_version
    if not model_version:
        model_version = datetime.now().strftime('%Y%m%d_%H%M%S')
        logger.info(f"Auto-generated model version: {model_version}")
    
    # Build common arguments
    common_args = ['--config', args.config]
    if args.data_mode:
        common_args.extend(['--data-mode', args.data_mode])
    
    # Pipeline start
    logger.info("=" * 80)
    logger.info("ATLAS TRAINING PIPELINE")
    logger.info("=" * 80)
    logger.info(f"Model Version: {model_version}")
    logger.info(f"Config: {args.config}")
    logger.info(f"Data Mode: {args.data_mode or config['data']['mode']}")
    logger.info(f"Dry Run: {args.dry_run}")
    logger.info("=" * 80)
    
    pipeline_start_time = datetime.now()
    
    try:
        # Step 1: Ingest Events
        if not args.skip_ingest:
            logger.info("\n[STEP 1/5] Ingesting Events...")
            step_args = common_args.copy()
            exit_code = run_step('training/ingest_events.py', step_args, args.dry_run)
            if exit_code != 0:
                logger.error("Pipeline failed at step 1: Event ingestion")
                return exit_code
        else:
            logger.info("\n[STEP 1/5] Skipping event ingestion (--skip-ingest)")
        
        # Step 2: Build Features
        if not args.skip_features:
            logger.info("\n[STEP 2/5] Building Features...")
            step_args = common_args.copy()
            # Pass ingested events path to feature building
            step_args.extend(['--events', config['data']['ingested_events']])
            exit_code = run_step('training/build_features.py', step_args, args.dry_run)
            if exit_code != 0:
                logger.error("Pipeline failed at step 2: Feature building")
                return exit_code
        else:
            logger.info("\n[STEP 2/5] Skipping feature building (--skip-features)")
        
        # Step 3: Train Candidate Models
        if not args.skip_candidates:
            logger.info("\n[STEP 3/5] Training Candidate Models...")
            step_args = common_args.copy()
            step_args.extend(['--model-version', model_version])
            # Pass ingested events path
            step_args.extend(['--events', config['data']['ingested_events']])
            # Pass features directory
            step_args.extend(['--features-dir', config['features']['output_dir']])
            exit_code = run_step('training/train_candidates.py', step_args, args.dry_run)
            if exit_code != 0:
                logger.error("Pipeline failed at step 3: Candidate model training")
                return exit_code
        else:
            logger.info("\n[STEP 3/5] Skipping candidate model training (--skip-candidates)")
        
        # Step 4: Train Ranker
        if not args.skip_ranker:
            logger.info("\n[STEP 4/5] Training LightGBM Ranker...")
            step_args = common_args.copy()
            step_args.extend(['--model-version', model_version])
            # Pass ingested events path
            step_args.extend(['--events', config['data']['ingested_events']])
            # Pass features directory
            step_args.extend(['--features-dir', config['features']['output_dir']])
            exit_code = run_step('training/train_ranker.py', step_args, args.dry_run)
            if exit_code != 0:
                logger.error("Pipeline failed at step 4: Ranker training")
                return exit_code
        else:
            logger.info("\n[STEP 4/5] Skipping ranker training (--skip-ranker)")
        
        # Step 5: Evaluate and Export
        if not args.skip_evaluation:
            logger.info("\n[STEP 5/5] Evaluating and Exporting...")
            step_args = common_args.copy()
            step_args.extend(['--model-version', model_version])
            # Pass ingested events path
            step_args.extend(['--events', config['data']['ingested_events']])
            # Pass features directory
            step_args.extend(['--features-dir', config['features']['output_dir']])
            if args.baseline:
                step_args.extend(['--baseline', args.baseline])
            exit_code = run_step('training/evaluate_and_export.py', step_args, args.dry_run)
            if exit_code != 0:
                logger.error("Pipeline failed at step 5: Evaluation")
                return exit_code
        else:
            logger.info("\n[STEP 5/5] Skipping evaluation (--skip-evaluation)")
        
        # Pipeline complete
        pipeline_end_time = datetime.now()
        duration = (pipeline_end_time - pipeline_start_time).total_seconds()
        
        logger.info("\n" + "=" * 80)
        logger.info("PIPELINE COMPLETE!")
        logger.info("=" * 80)
        logger.info(f"Model Version: {model_version}")
        logger.info(f"Duration: {duration:.1f} seconds ({duration/60:.1f} minutes)")
        logger.info(f"Artifacts saved to: notebooks/artifacts/models/{model_version}")
        logger.info("=" * 80)
        
        if not args.dry_run:
            logger.info("\nNext steps:")
            logger.info("1. Review run summary: notebooks/artifacts/models/{}/run_summary.json".format(model_version))
            logger.info("2. Update MODEL_VERSION in docker-compose.yml to: {}".format(model_version))
            logger.info("3. Restart recommendation-service: docker-compose restart recommendation-service")
        
        return 0
    
    except KeyboardInterrupt:
        logger.warning("\nPipeline interrupted by user")
        return 130
    
    except Exception as e:
        logger.error(f"\nPipeline failed with unexpected error: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
