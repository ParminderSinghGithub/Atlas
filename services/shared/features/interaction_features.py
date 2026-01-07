"""
User-item interaction feature computation.

Creates one row per (user_id, product_id) pair capturing interaction strength.
"""
import pandas as pd
import numpy as np


def compute_interaction_features(
    events_df: pd.DataFrame,
    reference_time: pd.Timestamp
) -> pd.DataFrame:
    """
    Compute user-item interaction features from event log.
    
    Args:
        events_df: Event log with columns:
            - user_id
            - product_id
            - event_id
            - event_type ('view', 'add_to_cart', 'purchase')
            - ts_datetime (timezone-aware timestamp)
        reference_time: Reference timestamp for recency computation
    
    Returns:
        DataFrame with one row per (user_id, product_id) pair, columns:
            - user_id (str)
            - product_id (int)
            - interaction_count (int)
            - last_interaction_ts (Timestamp)
            - has_purchased (int, 0 or 1)
            - recency_days (float)
    
    Feature Definitions:
        - interaction_count: Number of interactions between user and product
        - last_interaction_ts: Timestamp of most recent interaction between user and product
        - has_purchased: Binary flag (1 if user has purchased product, 0 otherwise)
        - recency_days: Days since last interaction (measured from reference_time)
    """
    # Basic aggregations per user-item pair
    interaction_features = events_df.groupby(['user_id', 'product_id']).agg(
        interaction_count=('event_id', 'count'),
        last_interaction_ts=('ts_datetime', 'max')
    ).reset_index()
    
    # Has purchased flag: check if user has any purchase event for this product
    purchase_flags = events_df[events_df['event_type'] == 'purchase'].groupby(['user_id', 'product_id']).size().reset_index(name='purchase_event_count')
    purchase_flags['has_purchased'] = 1
    purchase_flags = purchase_flags[['user_id', 'product_id', 'has_purchased']]
    
    # Merge purchase flags
    interaction_features = interaction_features.merge(purchase_flags, on=['user_id', 'product_id'], how='left')
    interaction_features['has_purchased'] = interaction_features['has_purchased'].fillna(0).astype(int)
    
    # Recency: days since last interaction (from reference time)
    interaction_features['recency_days'] = (reference_time - interaction_features['last_interaction_ts']).dt.total_seconds() / 86400
    
    return interaction_features
