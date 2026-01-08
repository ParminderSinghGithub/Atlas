"""
Evaluation and Export Script

Evaluates trained models, compares metrics against baseline, and exports run summary.
Includes git hash capture and data checksums for reproducibility.

Usage:
    python evaluate_and_export.py --config config.yaml --model-version v1
    python evaluate_and_export.py --config config.yaml --baseline previous_run_summary.json
"""

import argparse
import logging
from pathlib import Path
import pandas as pd
import numpy as np
import yaml
import sys
import json
import pickle
import hashlib
import subprocess
from datetime import datetime
from sklearn.metrics import ndcg_score

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


def get_git_hash() -> str:
    """Get current git commit hash."""
    try:
        result = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except Exception as e:
        logger.warning(f"Could not get git hash: {e}")
        return None


def compute_file_checksum(file_path: Path) -> str:
    """Compute MD5 checksum of file."""
    md5 = hashlib.md5()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b''):
            md5.update(chunk)
    return md5.hexdigest()


def load_features(features_dir: Path, config: dict) -> dict:
    """Load feature tables from parquet files."""
    logger.info(f"Loading features from {features_dir}")
    
    user_features = pd.read_parquet(
        features_dir / config['features']['user_features_file']
    )
    item_features = pd.read_parquet(
        features_dir / config['features']['item_features_file']
    )
    interaction_features = pd.read_parquet(
        features_dir / config['features']['interaction_features_file']
    )
    
    return {
        'user_features': user_features,
        'item_features': item_features,
        'interaction_features': interaction_features
    }


def load_events(config: dict, data_mode: str, events_path_override: Path = None) -> pd.DataFrame:
    """Load events for evaluation."""
    logger.info(f"Loading events (mode: {data_mode})")
    
    # If events path override is provided (from pipeline), use it
    if events_path_override:
        logger.info(f"Using provided events path: {events_path_override}")
        df_events = pd.read_parquet(events_path_override)
        logger.info(f"Loaded {len(df_events):,} events")
        return df_events
    
    # Otherwise, use config paths
    if data_mode == "retailrocket":
        events_path = Path(config['data']['retailrocket_events'])
    elif data_mode == "synthetic":
        events_dir = Path(config['data']['synthetic_events_dir'])
        parquet_files = list(events_dir.rglob('*.parquet'))
        df_events = pd.concat([pd.read_parquet(f) for f in parquet_files], ignore_index=True)
        return df_events
    elif data_mode == "merged":
        events_path = Path(config['data']['merged_events'])
    else:
        raise ValueError(f"Invalid data mode: {data_mode}")
    
    df_events = pd.read_parquet(events_path)
    return df_events


def create_validation_data(features: dict, events: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Create validation dataset with labels."""
    logger.info("Creating validation data...")
    
    # Merge features
    df_train = features['interaction_features'].copy()
    
    df_train = df_train.merge(
        features['user_features'].add_prefix('user_'),
        left_on='user_id',
        right_on='user_user_id',
        how='left'
    )
    
    df_train = df_train.merge(
        features['item_features'].add_prefix('item_'),
        left_on='product_id',
        right_on='item_product_id',
        how='left'
    )
    
    df_train = df_train.drop(columns=['user_user_id', 'item_product_id'])
    
    # Create labels
    label_config = config['training']['labels']
    event_labels = events.copy()
    event_labels['relevance'] = event_labels['event_type'].map(label_config)
    labels = event_labels.groupby(['user_id', 'product_id'])['relevance'].max().reset_index()
    
    df_train = df_train.merge(labels, on=['user_id', 'product_id'], how='left')
    
    # Extract validation set
    split_percentile = config['training']['split']['train_percentile']
    split_timestamp = df_train['last_interaction_ts'].quantile(split_percentile / 100)
    df_val_set = df_train[df_train['last_interaction_ts'] > split_timestamp].copy()
    
    logger.info(f"Validation set: {len(df_val_set):,} interactions")
    return df_val_set


def evaluate_lightgbm(model, X_val, y_val, group_val, config: dict) -> dict:
    """Evaluate LightGBM ranker with multiple metrics."""
    logger.info("Evaluating LightGBM ranker...")
    
    y_pred = model.predict(X_val)
    
    ndcg_scores = []
    recall_scores = []
    precision_scores = []
    
    k = 10  # Hardcoded from notebook
    
    start_idx = 0
    for group_size in group_val:
        end_idx = start_idx + group_size
        
        y_true_group = y_val.iloc[start_idx:end_idx].values
        y_pred_group = y_pred[start_idx:end_idx]
        
        # Skip small groups
        if len(y_true_group) < 2:
            start_idx = end_idx
            continue
        
        # Get top-k predictions
        top_k_indices = np.argsort(y_pred_group)[::-1][:k]
        
        # NDCG@k
        if np.sum(y_true_group) > 0:
            ndcg = ndcg_score([y_true_group], [y_pred_group], k=k)
            ndcg_scores.append(ndcg)
        
        # Recall@k and Precision@k
        relevant_items = np.where(y_true_group > 1)[0]
        if len(relevant_items) > 0:
            recall = len(set(top_k_indices) & set(relevant_items)) / len(relevant_items)
            recall_scores.append(recall)
            
            precision = len(set(top_k_indices) & set(relevant_items)) / min(k, len(top_k_indices))
            precision_scores.append(precision)
        
        start_idx = end_idx
    
    metrics = {
        'ndcg@10': float(np.mean(ndcg_scores)) if ndcg_scores else 0,
        'recall@10': float(np.mean(recall_scores)) if recall_scores else 0,
        'precision@10': float(np.mean(precision_scores)) if precision_scores else 0
    }
    
    logger.info("LightGBM Metrics:")
    for metric, value in metrics.items():
        logger.info(f"  {metric}: {value:.4f}")
    
    return metrics


def load_baseline_metrics(baseline_file: Path) -> dict:
    """Load baseline metrics from previous run."""
    if not baseline_file or not baseline_file.exists():
        logger.info("No baseline metrics provided")
        return None
    
    logger.info(f"Loading baseline metrics from {baseline_file}")
    with open(baseline_file, 'r') as f:
        baseline = json.load(f)
    
    # Extract metrics from baseline run summary
    if 'models_evaluated' in baseline and 'lightgbm_ranker' in baseline['models_evaluated']:
        return baseline['models_evaluated']['lightgbm_ranker']
    
    return None


def compare_metrics(current_metrics: dict, baseline_metrics: dict, config: dict) -> dict:
    """Compare current metrics against baseline and check for regressions."""
    if baseline_metrics is None:
        logger.info("No baseline comparison performed")
        return {
            'passed': True,
            'reason': 'No baseline provided',
            'comparison': {}
        }
    
    tolerance = config['evaluation']['regression_tolerance']
    
    comparison = {}
    regressions = []
    
    for metric_name in current_metrics.keys():
        if metric_name in baseline_metrics:
            current_val = current_metrics[metric_name]
            baseline_val = baseline_metrics[metric_name]
            delta = current_val - baseline_val
            delta_pct = (delta / baseline_val * 100) if baseline_val > 0 else 0
            
            comparison[metric_name] = {
                'current': current_val,
                'baseline': baseline_val,
                'delta': float(delta),
                'delta_pct': float(delta_pct)
            }
            
            # Check for regression
            if metric_name in tolerance:
                if delta < -tolerance[metric_name]:
                    regressions.append(f"{metric_name} dropped by {abs(delta_pct):.2f}%")
    
    passed = len(regressions) == 0
    
    logger.info("Metric Comparison:")
    for metric_name, comp in comparison.items():
        logger.info(f"  {metric_name}: {comp['current']:.4f} (baseline: {comp['baseline']:.4f}, Δ: {comp['delta_pct']:+.2f}%)")
    
    if not passed:
        logger.warning(f"Metric regressions detected: {regressions}")
    else:
        logger.info("No metric regressions detected")
    
    return {
        'passed': passed,
        'regressions': regressions if not passed else [],
        'comparison': comparison
    }


def create_run_summary(config: dict, data_mode: str, model_version: str, 
                      features: dict, events: pd.DataFrame, metrics: dict, 
                      comparison: dict, git_hash: str) -> dict:
    """Create comprehensive run summary."""
    logger.info("Creating run summary...")
    
    summary = {
        'execution_metadata': {
            'executed_at': datetime.now().isoformat(),
            'data_mode': data_mode,
            'model_version': model_version,
            'git_commit': git_hash,
            'pipeline_version': '1.0.0'
        },
        
        'dataset_statistics': {
            'events_loaded': len(events),
            'unique_users': int(events['user_id'].nunique()),
            'unique_products': int(events['product_id'].nunique()),
            'event_type_counts': {str(k): int(v) for k, v in events['event_type'].value_counts().to_dict().items()},
            'user_features_count': len(features['user_features']),
            'item_features_count': len(features['item_features']),
            'interaction_features_count': len(features['interaction_features'])
        },
        
        'models_evaluated': {
            'lightgbm_ranker': metrics
        },
        
        'metric_comparison': comparison,
        
        'reproducibility': {
            'git_commit': git_hash,
            'config_checksum': compute_file_checksum(Path('training/config.yaml')),
            'random_seed': config['execution']['random_seed']
        }
    }
    
    return summary


def save_run_summary(summary: dict, config: dict, model_version: str):
    """Save run summary to disk."""
    models_dir = Path(config['artifacts']['models_dir'])
    
    if model_version:
        output_dir = models_dir / model_version
    else:
        output_dir = models_dir
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    summary_file = output_dir / config['artifacts']['run_summary_file']
    logger.info(f"Saving run summary to {summary_file}")
    
    with open(summary_file, 'w') as f:
        json.dump(summary, f, indent=2)
    
    logger.info("Run summary saved")


def main():
    parser = argparse.ArgumentParser(
        description='Evaluate models and export run summary'
    )
    parser.add_argument(
        '--config',
        type=str,
        default='training/config.yaml',
        help='Path to configuration file'
    )
    parser.add_argument(
        '--features-dir',
        type=str,
        help='Override features directory from config'
    )
    parser.add_argument(
        '--model-version',
        type=str,
        help='Model version (e.g., v1, 20260107_120000)'
    )
    parser.add_argument(
        '--events',
        type=str,
        help='Path to events parquet file (optional - overrides config paths)'
    )
    parser.add_argument(
        '--data-mode',
        type=str,
        help='Override data mode from config'
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
    
    try:
        # Determine paths
        features_dir = Path(args.features_dir) if args.features_dir else Path(config['features']['output_dir'])
        data_mode = args.data_mode or config['data']['mode']
        model_version = args.model_version or config['artifacts'].get('version')
        
        # Get git hash
        git_hash = get_git_hash() if config['execution'].get('capture_git_hash', True) else None
        
        # Load features and events
        features = load_features(features_dir, config)
        events_path = Path(args.events) if args.events else None
        events = load_events(config, data_mode, events_path)
        
        # Create validation data
        df_val_set = create_validation_data(features, events, config)
        
        # Load trained LightGBM model
        models_dir = Path(config['artifacts']['models_dir'])
        output_dir = models_dir / model_version if model_version else models_dir
        
        model_file = output_dir / config['models']['lightgbm']['output_file']
        logger.info(f"Loading LightGBM model from {model_file}")
        
        import lightgbm as lgb
        lgb_model = lgb.Booster(model_file=str(model_file))
        
        # Prepare validation data for evaluation
        exclude_cols = config['models']['lightgbm']['exclude_columns']
        feature_cols = [col for col in df_val_set.columns if col not in exclude_cols]
        
        X_val = df_val_set[feature_cols].apply(pd.to_numeric, errors='coerce').fillna(0)
        y_val = df_val_set['relevance']
        group_val = df_val_set.groupby('user_id').size().values
        
        # Evaluate model
        metrics = evaluate_lightgbm(lgb_model, X_val, y_val, group_val, config)
        
        # Load baseline and compare
        baseline_file = Path(args.baseline) if args.baseline else config['evaluation'].get('baseline_metrics_file')
        baseline_metrics = load_baseline_metrics(baseline_file) if baseline_file else None
        comparison = compare_metrics(metrics, baseline_metrics, config)
        
        # Create run summary
        summary = create_run_summary(
            config, data_mode, model_version, features, events, 
            metrics, comparison, git_hash
        )
        
        # Save run summary
        save_run_summary(summary, config, model_version)
        
        # Exit with failure if metrics regressed
        if not comparison['passed']:
            logger.error("Evaluation failed: Metrics regressed beyond tolerance")
            return 1
        
        logger.info("Evaluation and export complete!")
        return 0
    
    except Exception as e:
        logger.error(f"Evaluation failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
