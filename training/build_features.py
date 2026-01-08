"""
Feature Building Script

Computes features using shared feature engineering modules.
Reuses exact logic from services/shared/features/ for training-serving parity.

Usage:
    python build_features.py --config config.yaml
    python build_features.py --config config.yaml --events path/to/events.parquet
"""

import argparse
import logging
from pathlib import Path
import pandas as pd
import yaml
import sys
import json
import hashlib
from datetime import datetime

# Add project root to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Import shared feature engineering modules
from services.shared.features import (
    get_reference_time,
    compute_user_features,
    compute_item_features,
    compute_interaction_features,
    USER_FEATURE_COLUMNS,
    ITEM_FEATURE_COLUMNS,
    INTERACTION_FEATURE_COLUMNS,
    validate_feature_schema
)

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


def load_events(events_path: Path) -> pd.DataFrame:
    """Load events from parquet."""
    logger.info(f"Loading events from {events_path}")
    df_events = pd.read_parquet(events_path)
    logger.info(f"Loaded {len(df_events):,} events")
    return df_events


def compute_schema_hash(df: pd.DataFrame) -> str:
    """Compute hash of dataframe schema (column names and dtypes)."""
    schema_str = str(sorted([(col, str(dtype)) for col, dtype in zip(df.columns, df.dtypes)]))
    return hashlib.md5(schema_str.encode()).hexdigest()[:8]


def build_features(config: dict, events_path: Path = None) -> dict:
    """
    Build features using shared feature modules.
    
    Args:
        config: Configuration dictionary
        events_path: Optional override for events path
    
    Returns:
        Dictionary with feature dataframes and metadata
    """
    # Load events
    if events_path is None:
        events_path = Path(config['data']['ingested_events'])
    df_events = load_events(events_path)
    
    # Ensure timestamp column is properly named and typed
    if 'ts' in df_events.columns and 'ts_datetime' not in df_events.columns:
        # Try to convert - could be ISO string or milliseconds
        try:
            df_events['ts_datetime'] = pd.to_datetime(df_events['ts'], utc=True)
        except:
            df_events['ts_datetime'] = pd.to_datetime(df_events['ts'], unit='ms', utc=True)
    elif 'timestamp' in df_events.columns and 'ts_datetime' not in df_events.columns:
        df_events['ts_datetime'] = pd.to_datetime(df_events['timestamp'], utc=True)
    
    # Get reference time
    reference_time_policy = config['features']['reference_time_policy']
    explicit_reference_time = config['features'].get('reference_time')
    
    logger.info(f"Reference time policy: {reference_time_policy}")
    if reference_time_policy == "explicit" and explicit_reference_time:
        logger.info(f"Using explicit reference time: {explicit_reference_time}")
        reference_time = pd.Timestamp(explicit_reference_time)
    else:
        logger.info("Inferring reference time from data")
        reference_time = get_reference_time(df_events)
        logger.info(f"Inferred reference time: {reference_time}")
    
    # Compute user features
    logger.info("Computing user features...")
    user_features = compute_user_features(df_events, reference_time)
    logger.info(f"Generated {len(user_features):,} user feature rows with {len(user_features.columns)} columns")
    
    # Validate user feature schema
    validate_feature_schema(user_features, USER_FEATURE_COLUMNS, "user")
    logger.info(f"User features schema validated: {USER_FEATURE_COLUMNS}")
    
    # Compute item features
    logger.info("Computing item features...")
    item_features = compute_item_features(df_events, reference_time)
    logger.info(f"Generated {len(item_features):,} item feature rows with {len(item_features.columns)} columns")
    
    # Validate item feature schema
    validate_feature_schema(item_features, ITEM_FEATURE_COLUMNS, "item")
    logger.info(f"Item features schema validated: {ITEM_FEATURE_COLUMNS}")
    
    # Compute interaction features
    logger.info("Computing interaction features...")
    interaction_features = compute_interaction_features(df_events, reference_time)
    logger.info(f"Generated {len(interaction_features):,} interaction feature rows with {len(interaction_features.columns)} columns")
    
    # Validate interaction feature schema
    validate_feature_schema(interaction_features, INTERACTION_FEATURE_COLUMNS, "interaction")
    logger.info(f"Interaction features schema validated: {INTERACTION_FEATURE_COLUMNS}")
    
    # Compute schema hashes for verification
    user_schema_hash = compute_schema_hash(user_features)
    item_schema_hash = compute_schema_hash(item_features)
    interaction_schema_hash = compute_schema_hash(interaction_features)
    
    # Build metadata
    metadata = {
        'created_at': datetime.now().isoformat(),
        'reference_time': str(reference_time),
        'reference_time_policy': reference_time_policy,
        'events_count': len(df_events),
        'user_features': {
            'row_count': len(user_features),
            'column_count': len(user_features.columns),
            'columns': list(user_features.columns),
            'schema_hash': user_schema_hash
        },
        'item_features': {
            'row_count': len(item_features),
            'column_count': len(item_features.columns),
            'columns': list(item_features.columns),
            'schema_hash': item_schema_hash
        },
        'interaction_features': {
            'row_count': len(interaction_features),
            'column_count': len(interaction_features.columns),
            'columns': list(interaction_features.columns),
            'schema_hash': interaction_schema_hash
        }
    }
    
    return {
        'user_features': user_features,
        'item_features': item_features,
        'interaction_features': interaction_features,
        'metadata': metadata
    }


def save_features(features: dict, config: dict, output_dir: Path = None):
    """Save features and metadata to disk."""
    if output_dir is None:
        output_dir = Path(config['features']['output_dir'])
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Save feature parquet files
    user_file = output_dir / config['features']['user_features_file']
    item_file = output_dir / config['features']['item_features_file']
    interaction_file = output_dir / config['features']['interaction_features_file']
    
    logger.info(f"Saving user features to {user_file}")
    features['user_features'].to_parquet(user_file, index=False)
    
    logger.info(f"Saving item features to {item_file}")
    features['item_features'].to_parquet(item_file, index=False)
    
    logger.info(f"Saving interaction features to {interaction_file}")
    features['interaction_features'].to_parquet(interaction_file, index=False)
    
    # Save metadata
    metadata_file = output_dir / config['features']['feature_metadata_file']
    logger.info(f"Saving feature metadata to {metadata_file}")
    with open(metadata_file, 'w') as f:
        json.dump(features['metadata'], f, indent=2)
    
    logger.info("Feature saving complete")


def main():
    parser = argparse.ArgumentParser(
        description='Build features for training pipeline'
    )
    parser.add_argument(
        '--config',
        type=str,
        default='training/config.yaml',
        help='Path to configuration file'
    )
    parser.add_argument(
        '--events',
        type=str,
        help='Override events path from config'
    )
    parser.add_argument(
        '--output-dir',
        type=str,
        help='Override output directory from config'
    )
    
    args = parser.parse_args()
    
    # Load configuration
    config = load_config(args.config)
    
    # Set log level
    log_level = config.get('execution', {}).get('log_level', 'INFO')
    logger.setLevel(getattr(logging, log_level))
    
    try:
        # Build features
        events_path = Path(args.events) if args.events else None
        features = build_features(config, events_path)
        
        # Save features
        output_dir = Path(args.output_dir) if args.output_dir else None
        save_features(features, config, output_dir)
        
        logger.info("Feature building complete!")
        return 0
    
    except Exception as e:
        logger.error(f"Feature building failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
