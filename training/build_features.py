"""
Feature Building Script.

Computes user, item, and interaction features using shared feature engineering modules.
Reuses exact logic from services/shared/features/ for training-serving parity.

Usage:
    python training/build_features.py --config training/config.yaml
    python training/build_features.py --config training/config.yaml --events path/to/events.parquet
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

# Add project root to sys.path for shared imports
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

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
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    return config


def load_events(events_path: Path) -> pd.DataFrame:
    """Load events from parquet."""
    logger.info(f"Loading events from {events_path}")
    if not events_path.exists():
        raise FileNotFoundError(f"Events file not found: {events_path}")
    df_events = pd.read_parquet(events_path)
    logger.info(f"Loaded {len(df_events):,} events")
    return df_events


def compute_schema_hash(df: pd.DataFrame) -> str:
    """Compute hash of dataframe schema (column names and dtypes)."""
    schema_str = str(sorted([(col, str(dtype)) for col, dtype in zip(df.columns, df.dtypes)]))
    return hashlib.sha256(schema_str.encode()).hexdigest()[:16]


def build_features(config: dict, events_path: Path = None) -> dict:
    """
    Build features using shared feature modules.
    
    Args:
        config: Configuration dictionary
        events_path: Optional override for events path
    
    Returns:
        Dictionary with feature dataframes and metadata
    """
    if events_path is None:
        events_path = Path(config['data']['ingested_events'])
        if not events_path.exists():
            events_path = Path.cwd() / events_path

    df_events = load_events(events_path)

    # Ensure timestamp column is properly named and typed
    if 'ts' in df_events.columns and 'ts_datetime' not in df_events.columns:
        try:
            df_events['ts_datetime'] = pd.to_datetime(df_events['ts'], utc=True)
        except Exception:
            df_events['ts_datetime'] = pd.to_datetime(df_events['ts'], unit='ms', utc=True)
    elif 'timestamp' in df_events.columns and 'ts_datetime' not in df_events.columns:
        df_events['ts_datetime'] = pd.to_datetime(df_events['timestamp'], utc=True)

    # Ensure event_id and session_id exist for aggregations
    if 'event_id' not in df_events.columns:
        df_events['event_id'] = range(1, len(df_events) + 1)
    if 'session_id' not in df_events.columns:
        df_events['session_id'] = df_events['user_id'].astype(str) + '_session_1'

    # Get reference time
    reference_time_policy = config['features']['reference_time_policy']
    explicit_reference_time = config['features'].get('reference_time')

    logger.info(f"Reference time policy: {reference_time_policy}")
    if reference_time_policy == "explicit" and explicit_reference_time:
        logger.info(f"Using explicit reference time: {explicit_reference_time}")
        reference_time = pd.Timestamp(explicit_reference_time)
    else:
        reference_time = get_reference_time(df_events)
        logger.info(f"Inferred reference time from data: {reference_time}")

    # 1. Compute user features
    logger.info("Computing user features...")
    user_features = compute_user_features(df_events, reference_time)
    logger.info(f"User features computed: {user_features.shape}")

    # 2. Compute item features
    logger.info("Computing item features...")
    item_features = compute_item_features(df_events, reference_time)
    logger.info(f"Item features computed: {item_features.shape}")

    # 3. Compute interaction features
    logger.info("Computing interaction features...")
    interaction_features = compute_interaction_features(df_events, reference_time)
    logger.info(f"Interaction features computed: {interaction_features.shape}")

    # Validate feature schemas
    logger.info("Validating feature schemas...")
    validate_feature_schema(user_features, USER_FEATURE_COLUMNS, "user_features")
    validate_feature_schema(item_features, ITEM_FEATURE_COLUMNS, "item_features")
    validate_feature_schema(interaction_features, INTERACTION_FEATURE_COLUMNS, "interaction_features")
    logger.info("All feature schemas validated successfully!")

    # Build metadata
    metadata = {
        'generated_at': datetime.now().isoformat(),
        'reference_time': reference_time.isoformat() if hasattr(reference_time, 'isoformat') else str(reference_time),
        'reference_time_policy': reference_time_policy,
        'events_source': str(events_path),
        'events_count': len(df_events),
        'user_features': {
            'rows': len(user_features),
            'columns': list(user_features.columns),
            'schema_hash': compute_schema_hash(user_features)
        },
        'item_features': {
            'rows': len(item_features),
            'columns': list(item_features.columns),
            'schema_hash': compute_schema_hash(item_features)
        },
        'interaction_features': {
            'rows': len(interaction_features),
            'columns': list(interaction_features.columns),
            'schema_hash': compute_schema_hash(interaction_features)
        }
    }

    return {
        'user_features': user_features,
        'item_features': item_features,
        'interaction_features': interaction_features,
        'metadata': metadata
    }


def save_features(features_dict: dict, output_dir: Path, config: dict):
    """Save features to parquet and metadata to JSON."""
    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Saving features to {output_dir}")

    user_file = output_dir / config['features']['user_features_file']
    item_file = output_dir / config['features']['item_features_file']
    interaction_file = output_dir / config['features']['interaction_features_file']
    meta_file = output_dir / config['features']['feature_metadata_file']

    logger.info(f"Saving user features to {user_file}")
    features_dict['user_features'].to_parquet(user_file, index=False)

    logger.info(f"Saving item features to {item_file}")
    features_dict['item_features'].to_parquet(item_file, index=False)

    logger.info(f"Saving interaction features to {interaction_file}")
    features_dict['interaction_features'].to_parquet(interaction_file, index=False)

    logger.info(f"Saving feature metadata to {meta_file}")
    with open(meta_file, 'w', encoding='utf-8') as f:
        json.dump(features_dict['metadata'], f, indent=2)

    logger.info("All feature tables saved successfully!")


def main():
    parser = argparse.ArgumentParser(
        description='Build features for recommender training'
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
        help='Path to events parquet file (optional override)'
    )
    parser.add_argument(
        '--data-mode',
        type=str,
        help='Override data mode from config'
    )
    parser.add_argument(
        '--output-dir',
        type=str,
        help='Override feature output directory'
    )

    args, _ = parser.parse_known_args()

    config = load_config(args.config)
    log_level = config.get('execution', {}).get('log_level', 'INFO')
    logger.setLevel(getattr(logging, log_level))

    try:
        events_path = Path(args.events) if args.events else None
        features_dict = build_features(config, events_path)

        output_dir = Path(args.output_dir) if args.output_dir else Path(config['features']['output_dir'])
        save_features(features_dict, output_dir, config)

        logger.info("Feature engineering complete!")
        return 0

    except Exception as e:
        logger.error(f"Feature engineering failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
