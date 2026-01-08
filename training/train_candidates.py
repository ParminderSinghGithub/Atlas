"""
Candidate Model Training Script

Trains candidate generation models:
- SVD (Collaborative Filtering)
- Item-Item Similarity

Note: Popularity is NOT trained - it's derived from item_features.parquet at serving time

Exact hyperparameters from notebooks/04_model_training.ipynb preserved.

Usage:
    python train_candidates.py --config config.yaml --model-version v1
    python train_candidates.py --config config.yaml --features-dir path/to/features
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
from datetime import datetime
from collections import defaultdict
from scipy.sparse import csr_matrix
from sklearn.decomposition import TruncatedSVD

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
        (df_train, df_train_set, df_val_set)
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
    logger.info(f"Label distribution:\n{labels['relevance'].value_counts().sort_index()}")
    
    # Merge labels into training data
    df_train = df_train.merge(labels, on=['user_id', 'product_id'], how='left')
    logger.info(f"Missing labels: {df_train['relevance'].isna().sum()}")
    logger.info(f"Final training data: {df_train.shape}")
    
    # Time-based train/validation split
    split_config = config['training']['split']
    split_percentile = split_config['train_percentile']
    split_timestamp = df_train['last_interaction_ts'].quantile(split_percentile / 100)
    
    train_mask = df_train['last_interaction_ts'] <= split_timestamp
    val_mask = df_train['last_interaction_ts'] > split_timestamp
    
    df_train_set = df_train[train_mask].copy()
    df_val_set = df_train[val_mask].copy()
    
    logger.info(f"Split timestamp: {split_timestamp}")
    logger.info(f"Train set: {df_train_set.shape[0]:,} interactions ({train_mask.sum() / len(df_train) * 100:.1f}%)")
    logger.info(f"Val set: {df_val_set.shape[0]:,} interactions ({val_mask.sum() / len(df_train) * 100:.1f}%)")
    
    return df_train, df_train_set, df_val_set


def train_svd_model(df_train_set: pd.DataFrame, df_val_set: pd.DataFrame, config: dict) -> dict:
    """Train SVD collaborative filtering model."""
    if not config['models']['svd']['enabled']:
        logger.info("SVD model disabled, skipping")
        return None
    
    logger.info("Training SVD model...")
    
    # Create sparse user-item interaction matrix
    logger.info("Building sparse interaction matrix...")
    
    # Create mappings for user and product IDs (include train + val for mapping)
    all_user_ids = pd.concat([df_train_set['user_id'], df_val_set['user_id']]).unique()
    all_product_ids = pd.concat([df_train_set['product_id'], df_val_set['product_id']]).unique()
    
    user_id_to_idx = {uid: idx for idx, uid in enumerate(all_user_ids)}
    product_id_to_idx = {pid: idx for idx, pid in enumerate(all_product_ids)}
    
    # Map IDs to indices (only for training data)
    row_indices = df_train_set['user_id'].map(user_id_to_idx).values
    col_indices = df_train_set['product_id'].map(product_id_to_idx).values
    data = df_train_set['relevance'].values
    
    # Create sparse matrix (CSR format)
    interaction_matrix_sparse = csr_matrix(
        (data, (row_indices, col_indices)),
        shape=(len(all_user_ids), len(all_product_ids))
    )
    
    logger.info(f"Shape: {interaction_matrix_sparse.shape} (users × products)")
    logger.info(f"Non-zero entries: {interaction_matrix_sparse.nnz:,}")
    sparsity = 100 * (1 - interaction_matrix_sparse.nnz / (interaction_matrix_sparse.shape[0] * interaction_matrix_sparse.shape[1]))
    logger.info(f"Sparsity: {sparsity:.4f}%")
    
    # Train SVD model
    svd_config = config['models']['svd']
    n_components = svd_config['n_components']
    random_state = svd_config['random_state']
    
    logger.info(f"Training SVD with n_components={n_components}, random_state={random_state}")
    svd_model = TruncatedSVD(n_components=n_components, random_state=random_state)
    user_factors = svd_model.fit_transform(interaction_matrix_sparse)
    item_factors = svd_model.components_.T
    
    logger.info(f"User factors: {user_factors.shape}")
    logger.info(f"Item factors: {item_factors.shape}")
    logger.info(f"Explained variance: {svd_model.explained_variance_ratio_.sum():.4f}")
    
    return {
        'model': svd_model,
        'user_factors': user_factors,
        'item_factors': item_factors,
        'user_id_to_idx': user_id_to_idx,
        'product_id_to_idx': product_id_to_idx,
        'metadata': {
            'n_components': n_components,
            'explained_variance': float(svd_model.explained_variance_ratio_.sum()),
            'matrix_shape': list(interaction_matrix_sparse.shape),
            'matrix_nnz': int(interaction_matrix_sparse.nnz),
            'sparsity_pct': float(sparsity)
        }
    }


def train_item_similarity(df_train_set: pd.DataFrame, config: dict) -> dict:
    """Train item-item co-visitation similarity model."""
    if not config['models']['item_similarity']['enabled']:
        logger.info("Item similarity model disabled, skipping")
        return None
    
    logger.info("Training item-item co-visitation similarity...")
    
    similarity_config = config['models']['item_similarity']
    MAX_SESSION_SIZE = similarity_config['max_session_size']
    MIN_COVISITS = similarity_config['min_covisits']
    
    # Group by user session and collect viewed items
    user_sessions = df_train_set.groupby('user_id')['product_id'].apply(list).values
    
    # Count co-occurrences
    covisit_counts = defaultdict(lambda: defaultdict(int))
    item_counts = defaultdict(int)
    
    sessions_processed = 0
    sessions_skipped = 0
    
    for session in user_sessions:
        # Skip sessions that are too large
        if len(session) > MAX_SESSION_SIZE:
            sessions_skipped += 1
            continue
        
        sessions_processed += 1
        
        # Increment item counts
        for item in session:
            item_counts[item] += 1
        
        # Increment co-occurrence counts
        for i, item1 in enumerate(session):
            for item2 in session[i+1:]:
                covisit_counts[item1][item2] += 1
                covisit_counts[item2][item1] += 1
        
        # Progress indicator
        if sessions_processed % 10000 == 0:
            logger.info(f"  Processed {sessions_processed:,} sessions ({sessions_skipped:,} skipped)")
    
    logger.info(f"Sessions processed: {sessions_processed:,}, skipped: {sessions_skipped:,}")
    
    # Calculate similarity scores (Jaccard-like: co-occurrence / sqrt(count1 * count2))
    item_similarity = {}
    
    for item1, related_items in covisit_counts.items():
        item_similarity[item1] = {}
        for item2, co_count in related_items.items():
            # Filter out weak relationships
            if co_count >= MIN_COVISITS:
                # Normalized by geometric mean of individual counts
                similarity = co_count / np.sqrt(item_counts[item1] * item_counts[item2])
                item_similarity[item1][item2] = similarity
    
    logger.info(f"Item similarity computed")
    logger.info(f"   Items with neighbors: {len(item_similarity):,}")
    avg_neighbors = np.mean([len(v) for v in item_similarity.values()])
    logger.info(f"   Avg neighbors per item: {avg_neighbors:.1f}")
    
    return {
        'similarity': item_similarity,
        'item_counts': dict(item_counts),
        'metadata': {
            'items_with_neighbors': len(item_similarity),
            'avg_neighbors_per_item': float(avg_neighbors),
            'sessions_processed': sessions_processed,
            'sessions_skipped': sessions_skipped
        }
    }


def save_candidate_models(svd_artifacts, item_similarity_artifacts, 
                         config: dict, model_version: str):
    """Save candidate models to disk."""
    models_dir = Path(config['artifacts']['models_dir'])
    
    # Create version subdirectory
    if model_version:
        output_dir = models_dir / model_version
    else:
        output_dir = models_dir
    
    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Saving candidate models to {output_dir}")
    
    # Note: Popularity is NOT saved as a model artifact
    # It's a derived aggregation computed from item_features.parquet at serving time
    # Serving has fallback logic: load .pkl if exists, else compute dynamically
    
    # Save SVD model
    if svd_artifacts is not None:
        svd_file = output_dir / config['models']['svd']['output_file']
        logger.info(f"Saving SVD model to {svd_file}")
        with open(svd_file, 'wb') as f:
            pickle.dump(svd_artifacts, f)
    
    # Save item similarity
    if item_similarity_artifacts is not None:
        similarity_file = output_dir / config['models']['item_similarity']['output_file']
        logger.info(f"Saving item similarity to {similarity_file}")
        with open(similarity_file, 'wb') as f:
            pickle.dump({
                'similarity': item_similarity_artifacts['similarity'],
                'item_counts': item_similarity_artifacts['item_counts'],
                'created_at': datetime.now().isoformat()
            }, f)
    
    # Save metadata summary
    metadata = {
        'created_at': datetime.now().isoformat(),
        'model_version': model_version,
        'models': {},
        'notes': {
            'popularity': 'Derived from item_features.parquet at serving time (not versioned)'
        }
    }
    
    if svd_artifacts is not None:
        metadata['models']['svd'] = svd_artifacts['metadata']
    
    if item_similarity_artifacts is not None:
        metadata['models']['item_similarity'] = item_similarity_artifacts['metadata']
    
    metadata_file = output_dir / 'candidate_models_metadata.json'
    logger.info(f"Saving metadata to {metadata_file}")
    with open(metadata_file, 'w') as f:
        json.dump(metadata, f, indent=2)
    
    logger.info("Candidate model saving complete")


def main():
    parser = argparse.ArgumentParser(
        description='Train candidate generation models'
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
        df_train, df_train_set, df_val_set = create_training_data(features, events, config)
        
        # Train candidate models (popularity is derived, not trained)
        svd_artifacts = train_svd_model(df_train_set, df_val_set, config)
        item_similarity_artifacts = train_item_similarity(df_train_set, config)
        
        # Validate item features exist (required for popularity computation at serving)
        logger.info("Validating item features availability for popularity computation...")
        features_dir = Path(args.features_dir) if args.features_dir else Path(config['features']['output_dir'])
        item_features_path = features_dir / config['features']['item_features_file']
        if not item_features_path.exists():
            logger.error(f"Item features not found at {item_features_path} - required for popularity fallback")
            raise FileNotFoundError(f"Item features required: {item_features_path}")
        logger.info(f"✓ Item features validated at {item_features_path}")
        
        # Save models
        model_version = args.model_version or config['artifacts'].get('version')
        save_candidate_models(svd_artifacts, item_similarity_artifacts, 
                            config, model_version)
        
        logger.info("Candidate model training complete!")
        return 0
    
    except Exception as e:
        logger.error(f"Candidate model training failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
