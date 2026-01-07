"""
Item-level feature computation.

Creates one row per product with aggregate features capturing popularity
and quality signals.
"""
import pandas as pd
import numpy as np


def compute_item_features(
    events_df: pd.DataFrame,
    reference_time: pd.Timestamp
) -> pd.DataFrame:
    """
    Compute item-level features from event log.
    
    Args:
        events_df: Event log with columns:
            - product_id
            - event_type ('view', 'add_to_cart', 'purchase')
            - ts_datetime (timezone-aware timestamp)
        reference_time: Reference timestamp for recency computation
    
    Returns:
        DataFrame with one row per product, columns:
            - product_id (int)
            - last_interaction_ts (Timestamp)
            - total_views (int)
            - total_add_to_cart (int)
            - total_purchases (int)
            - popularity_score (float)
            - conversion_rate (float)
            - recency_days (float)
    
    Feature Definitions:
        - last_interaction_ts: Timestamp of most recent interaction with product
        - total_views: Number of view events for this product
        - total_add_to_cart: Number of add-to-cart events
        - total_purchases: Number of purchase events
        - popularity_score: Log-scaled popularity metric (log1p of total interactions)
        - conversion_rate: Purchase conversion rate (total_purchases / total_views)
        - recency_days: Days since last interaction (measured from reference_time)
    """
    # Basic aggregations per product
    item_features = events_df.groupby('product_id').agg(
        last_interaction_ts=('ts_datetime', 'max')
    ).reset_index()
    
    # Event type counts per product
    item_event_counts = events_df.groupby(['product_id', 'event_type']).size().unstack(fill_value=0)
    item_event_counts = item_event_counts.reset_index()
    
    # Rename columns to match requirements
    item_column_mapping = {
        'view': 'total_views',
        'add_to_cart': 'total_add_to_cart',
        'purchase': 'total_purchases'
    }
    
    item_event_counts = item_event_counts.rename(columns=item_column_mapping)
    
    # Ensure all required columns exist
    for col in ['total_views', 'total_add_to_cart', 'total_purchases']:
        if col not in item_event_counts.columns:
            item_event_counts[col] = 0
    
    # Drop 'click' column if it exists
    if 'click' in item_event_counts.columns:
        item_event_counts = item_event_counts.drop(columns=['click'])
    
    # Merge event counts with item features
    item_features = item_features.merge(item_event_counts, on='product_id', how='left')
    
    # Fill any NaN values with 0
    item_features['total_views'] = item_features['total_views'].fillna(0).astype(int)
    item_features['total_add_to_cart'] = item_features['total_add_to_cart'].fillna(0).astype(int)
    item_features['total_purchases'] = item_features['total_purchases'].fillna(0).astype(int)
    
    # Popularity score: log-scaled total interactions
    total_interactions = item_features['total_views'] + item_features['total_add_to_cart'] + item_features['total_purchases']
    item_features['popularity_score'] = np.log1p(total_interactions)
    
    # Conversion rate: purchases / views (avoid division by zero)
    item_features['conversion_rate'] = item_features['total_purchases'] / item_features['total_views'].replace(0, np.nan)
    item_features['conversion_rate'] = item_features['conversion_rate'].fillna(0)
    
    # Recency: days since last interaction (from reference time)
    item_features['recency_days'] = (reference_time - item_features['last_interaction_ts']).dt.total_seconds() / 86400
    
    return item_features
