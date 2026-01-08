"""
Event Ingestion Script

Loads RetailRocket events and optionally app events based on configuration.
Outputs a unified events.parquet file for feature engineering.

Usage:
    python ingest_events.py --config config.yaml
    python ingest_events.py --config config.yaml --data-mode synthetic
"""

import argparse
import logging
from pathlib import Path
import pandas as pd
import yaml
import sys

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


def load_retailrocket_events(path: Path) -> pd.DataFrame:
    """Load RetailRocket events from parquet."""
    logger.info(f"Loading RetailRocket events from {path}")
    df = pd.read_parquet(path)
    logger.info(f"Loaded {len(df):,} events")
    return df


def load_synthetic_events(directory: Path) -> pd.DataFrame:
    """Load synthetic events from directory of parquet files."""
    logger.info(f"Loading synthetic events from {directory}")
    parquet_files = list(directory.rglob("*.parquet"))
    
    if not parquet_files:
        raise FileNotFoundError(f"No parquet files found in {directory}")
    
    logger.info(f"Found {len(parquet_files)} parquet files")
    dfs = []
    for file in parquet_files:
        df = pd.read_parquet(file)
        dfs.append(df)
    
    df_combined = pd.concat(dfs, ignore_index=True)
    logger.info(f"Loaded {len(df_combined):,} synthetic events")
    return df_combined


def load_merged_events(path: Path) -> pd.DataFrame:
    """Load merged events (demo dataset)."""
    logger.info(f"Loading merged events from {path}")
    df = pd.read_parquet(path)
    logger.info(f"Loaded {len(df):,} events")
    return df


def ingest_events(config: dict, data_mode: str = None) -> pd.DataFrame:
    """
    Load events based on configuration.
    
    Args:
        config: Configuration dictionary
        data_mode: Override data mode (retailrocket, synthetic, merged)
    
    Returns:
        DataFrame with unified events
    """
    # Determine data mode
    mode = data_mode or config['data']['mode']
    logger.info(f"Data mode: {mode}")
    
    # Load events based on mode
    if mode == "retailrocket":
        path = Path(config['data']['retailrocket_events'])
        df_events = load_retailrocket_events(path)
    
    elif mode == "synthetic":
        path = Path(config['data']['synthetic_events_dir'])
        df_events = load_synthetic_events(path)
    
    elif mode == "merged":
        path = Path(config['data']['merged_events'])
        df_events = load_merged_events(path)
    
    else:
        raise ValueError(
            f"Invalid data mode: {mode}. "
            f"Use 'retailrocket', 'synthetic', or 'merged'"
        )
    
    # Validate schema
    required_columns = ['user_id', 'product_id', 'event_type', 'ts']
    missing_cols = [col for col in required_columns if col not in df_events.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns: {missing_cols}")
    
    # Log statistics
    logger.info(f"Event statistics:")
    logger.info(f"  Total events: {len(df_events):,}")
    logger.info(f"  Unique users: {df_events['user_id'].nunique():,}")
    logger.info(f"  Unique products: {df_events['product_id'].nunique():,}")
    logger.info(f"  Event types: {df_events['event_type'].unique().tolist()}")
    logger.info(f"  Event type distribution:")
    for event_type, count in df_events['event_type'].value_counts().items():
        logger.info(f"    {event_type}: {count:,}")
    
    return df_events


def save_events(df_events: pd.DataFrame, output_path: Path):
    """Save events to parquet."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info(f"Saving events to {output_path}")
    df_events.to_parquet(output_path, index=False)
    logger.info(f"Saved {len(df_events):,} events")


def main():
    parser = argparse.ArgumentParser(
        description='Ingest events for training pipeline'
    )
    parser.add_argument(
        '--config',
        type=str,
        default='training/config.yaml',
        help='Path to configuration file'
    )
    parser.add_argument(
        '--data-mode',
        type=str,
        choices=['retailrocket', 'synthetic', 'merged'],
        help='Override data mode from config'
    )
    parser.add_argument(
        '--output',
        type=str,
        help='Override output path from config'
    )
    
    args = parser.parse_args()
    
    # Load configuration
    config = load_config(args.config)
    
    # Set log level
    log_level = config.get('execution', {}).get('log_level', 'INFO')
    logger.setLevel(getattr(logging, log_level))
    
    try:
        # Ingest events
        df_events = ingest_events(config, args.data_mode)
        
        # Determine output path
        output_path = Path(args.output) if args.output else Path(config['data']['ingested_events'])
        
        # Save events
        save_events(df_events, output_path)
        
        logger.info("Event ingestion complete!")
        return 0
    
    except Exception as e:
        logger.error(f"Event ingestion failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
