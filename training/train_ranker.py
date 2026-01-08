"""
LightGBM Ranker Training Script

Trains LightGBM ranking model for final recommendation re-ranking.
Exact hyperparameters from notebooks/04_model_training.ipynb preserved.

Usage:
    python train_ranker.py --config config.yaml --model-version v1
    python train_ranker.py --config config.yaml --features-dir path/to/features
"""

import argparse
import logging
from pathlib import Path
import pandas as pd
import numpy as np
import yaml
import sys
import json
import lightgbm as lgb
from datetime import datetime

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
    
    logger.info(f"User features: {user_features.shape}")
    logger.info(f"Item features: {item_features.shape}")
    logger.info(f"Interaction features: {interaction_features.shape}")
    
    return {
        'user_features': user_features,
        'item_features': item_features,
        'interaction_features': interaction_features
    }


def load_events(config: dict, data_mode: str, events_path_override: Path = None) -> pd.DataFrame:
    """Load events for label engineering."""
    logger.info(f"Loading events for label engineering (mode: {data_mode})")
    
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
        logger.info(f"Loaded {len(df_events):,} events")
        return df_events
    elif data_mode == "merged":
        events_path = Path(config['data']['merged_events'])
    else:
        raise ValueError(f"Invalid data mode: {data_mode}")
    
    df_events = pd.read_parquet(events_path)
    logger.info(f"Loaded {len(df_events):,} events")
    return df_events


def create_training_data(features: dict, events: pd.DataFrame, config: dict) -> tuple:
    """
    Merge features and create labeled training data.
    
    Returns:
        (df_train_set, df_val_set, feature_cols)
    """
    logger.info("Creating training data...")
    
    # Merge interaction features with user and item features
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
    logger.info(f"Merged training data: {df_train.shape}")
    
    # Create relevance labels from event types
    label_config = config['training']['labels']
    event_labels = events.copy()
    event_labels['relevance'] = event_labels['event_type'].map(label_config)
    
    # Take maximum relevance per user-product pair
    labels = event_labels.groupby(['user_id', 'product_id'])['relevance'].max().reset_index()
    logger.info(f"Labels created: {labels.shape}")
    
    # Merge labels into training data
    df_train = df_train.merge(labels, on=['user_id', 'product_id'], how='left')
    
    # Time-based train/validation split
    split_config = config['training']['split']
    split_percentile = split_config['train_percentile']
    split_timestamp = df_train['last_interaction_ts'].quantile(split_percentile / 100)
    
    train_mask = df_train['last_interaction_ts'] <= split_timestamp
    val_mask = df_train['last_interaction_ts'] > split_timestamp
    
    df_train_set = df_train[train_mask].copy()
    df_val_set = df_train[val_mask].copy()
    
    logger.info(f"Split timestamp: {split_timestamp}")
    logger.info(f"Train set: {df_train_set.shape[0]:,} interactions")
    logger.info(f"Val set: {df_val_set.shape[0]:,} interactions")
    
    # Prepare feature columns (exclude IDs, timestamps, and labels)
    exclude_cols = config['models']['lightgbm']['exclude_columns']
    feature_cols = [col for col in df_train_set.columns if col not in exclude_cols]
    
    logger.info(f"Features for LightGBM: {len(feature_cols)}")
    logger.info(f"Feature columns: {feature_cols}")
    
    return df_train_set, df_val_set, feature_cols


def train_lightgbm_ranker(df_train_set: pd.DataFrame, df_val_set: pd.DataFrame, 
                         feature_cols: list, config: dict) -> dict:
    """Train LightGBM ranking model."""
    if not config['models']['lightgbm']['enabled']:
        logger.info("LightGBM ranker disabled, skipping")
        return None
    
    logger.info("Training LightGBM Ranker...")
    
    # Prepare training data
    X_train = df_train_set[feature_cols].apply(pd.to_numeric, errors='coerce').fillna(0)
    y_train = df_train_set['relevance']
    group_train = df_train_set.groupby('user_id').size().values
    
    X_val = df_val_set[feature_cols].apply(pd.to_numeric, errors='coerce').fillna(0)
    y_val = df_val_set['relevance']
    group_val = df_val_set.groupby('user_id').size().values
    
    logger.info(f"X_train: {X_train.shape}, groups: {len(group_train)}")
    logger.info(f"X_val:   {X_val.shape}, groups: {len(group_val)}")
    
    # Create LightGBM datasets
    lgb_train = lgb.Dataset(X_train, y_train, group=group_train)
    lgb_val = lgb.Dataset(X_val, y_val, group=group_val, reference=lgb_train)
    
    # Get hyperparameters from config
    lgb_config = config['models']['lightgbm']
    params = {
        'objective': lgb_config['objective'],
        'metric': lgb_config['metric'],
        'ndcg_eval_at': lgb_config['ndcg_eval_at'],
        'learning_rate': lgb_config['learning_rate'],
        'num_leaves': lgb_config['num_leaves'],
        'feature_fraction': lgb_config['feature_fraction'],
        'bagging_fraction': lgb_config['bagging_fraction'],
        'bagging_freq': lgb_config['bagging_freq'],
        'verbose': lgb_config['verbose'],
        'seed': lgb_config['seed']
    }
    
    logger.info(f"LightGBM parameters: {params}")
    
    # Train model
    num_boost_round = lgb_config['num_boost_round']
    logger.info(f"Training for {num_boost_round} rounds...")
    
    lgb_model = lgb.train(
        params,
        lgb_train,
        num_boost_round=num_boost_round,
        valid_sets=[lgb_train, lgb_val],
        valid_names=['train', 'val']
    )
    
    logger.info("Training complete!")
    
    # Extract feature importance
    feature_importance = pd.DataFrame({
        'feature': feature_cols,
        'importance': lgb_model.feature_importance(importance_type='gain')
    }).sort_values('importance', ascending=False)
    
    logger.info("\nTop 10 Most Important Features:")
    logger.info(feature_importance.head(10).to_string(index=False))
    
    return {
        'model': lgb_model,
        'feature_cols': feature_cols,
        'feature_importance': feature_importance,
        'params': params,
        'num_boost_round': num_boost_round
    }


def save_ranker_model(lgb_artifacts: dict, config: dict, model_version: str):
    """Save LightGBM ranker model to disk."""
    if lgb_artifacts is None:
        logger.info("No LightGBM artifacts to save")
        return
    
    models_dir = Path(config['artifacts']['models_dir'])
    
    # Create version subdirectory
    if model_version:
        output_dir = models_dir / model_version
    else:
        output_dir = models_dir
    
    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Saving LightGBM ranker to {output_dir}")
    
    # Save model
    model_file = output_dir / config['models']['lightgbm']['output_file']
    logger.info(f"Saving model to {model_file}")
    lgb_artifacts['model'].save_model(str(model_file))
    
    # Save feature importance
    importance_file = output_dir / config['artifacts']['feature_importance_file']
    logger.info(f"Saving feature importance to {importance_file}")
    lgb_artifacts['feature_importance'].to_csv(importance_file, index=False)
    
    # Save metadata
    metadata = {
        'model_type': 'LightGBM Ranker',
        'trained_at': datetime.now().isoformat(),
        'model_version': model_version,
        'features': lgb_artifacts['feature_cols'],
        'n_features': len(lgb_artifacts['feature_cols']),
        'hyperparameters': lgb_artifacts['params'],
        'num_boost_round': lgb_artifacts['num_boost_round'],
        'top_10_features': [
            {'feature': row['feature'], 'importance': float(row['importance'])}
            for _, row in lgb_artifacts['feature_importance'].head(10).iterrows()
        ]
    }
    
    metadata_file = output_dir / 'ranker_metadata.json'
    logger.info(f"Saving metadata to {metadata_file}")
    with open(metadata_file, 'w') as f:
        json.dump(metadata, f, indent=2)
    
    logger.info("LightGBM ranker saving complete")


def main():
    parser = argparse.ArgumentParser(
        description='Train LightGBM ranking model'
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
        help='Model version for artifact storage (e.g., v1, 20260107_120000)'
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
    
    args = parser.parse_args()
    
    # Load configuration
    config = load_config(args.config)
    
    # Set log level
    log_level = config.get('execution', {}).get('log_level', 'INFO')
    logger.setLevel(getattr(logging, log_level))
    
    try:
        # Determine features directory
        features_dir = Path(args.features_dir) if args.features_dir else Path(config['features']['output_dir'])
        
        # Load features
        features = load_features(features_dir, config)
        
        # Load events for label engineering
        data_mode = args.data_mode or config['data']['mode']
        events_path = Path(args.events) if args.events else None
        events = load_events(config, data_mode, events_path)
        
        # Create training data
        df_train_set, df_val_set, feature_cols = create_training_data(features, events, config)
        
        # Train LightGBM ranker
        lgb_artifacts = train_lightgbm_ranker(df_train_set, df_val_set, feature_cols, config)
        
        # Save model
        model_version = args.model_version or config['artifacts'].get('version')
        save_ranker_model(lgb_artifacts, config, model_version)
        
        logger.info("LightGBM ranker training complete!")
        return 0
    
    except Exception as e:
        logger.error(f"LightGBM ranker training failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
