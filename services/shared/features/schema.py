"""
Feature schema definitions for Atlas recommendation system.

CRITICAL: These column lists define the exact schema expected by:
1. Training notebooks (feature engineering)
2. Parquet storage (artifact format)
3. LightGBM ranker (feature order is CRITICAL)
4. Serving feature loader (lookup keys)

DO NOT modify column order or names without coordinating across all consumers.
"""

# User Features Schema
# Order matches: notebooks/artifacts/features/retailrocket/user_features.parquet
USER_FEATURE_COLUMNS = [
    'user_id',
    'total_events',
    'unique_products_interacted',
    'unique_sessions',
    'last_event_ts',
    'views_count',
    'add_to_cart_count',
    'purchase_count',
    'recency_days'
]

# Item Features Schema
# Order matches: notebooks/artifacts/features/retailrocket/item_features.parquet
ITEM_FEATURE_COLUMNS = [
    'product_id',
    'last_interaction_ts',
    'total_views',
    'total_add_to_cart',
    'total_purchases',
    'popularity_score',
    'conversion_rate',
    'recency_days'
]

# Interaction Features Schema
# Order matches: notebooks/artifacts/features/retailrocket/interaction_features.parquet
INTERACTION_FEATURE_COLUMNS = [
    'user_id',
    'product_id',
    'interaction_count',
    'last_interaction_ts',
    'has_purchased',
    'recency_days'
]

# LightGBM Feature Names (from model_metadata.json)
# CRITICAL: Order must match training data column order
LIGHTGBM_FEATURE_NAMES = [
    'interaction_count',
    'has_purchased',
    'recency_days',
    'user_total_events',
    'user_unique_products_interacted',
    'user_unique_sessions',
    'user_add_to_cart_count',
    'user_purchase_count',
    'user_views_count',
    'user_recency_days',
    'item_total_add_to_cart',
    'item_total_purchases',
    'item_total_views',
    'item_popularity_score',
    'item_conversion_rate',
    'item_recency_days'
]


def validate_user_features(df):
    """
    Validate user features DataFrame against schema.
    
    Args:
        df: User features DataFrame
    
    Raises:
        ValueError: If schema validation fails
    """
    missing = set(USER_FEATURE_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"Missing user feature columns: {missing}")
    
    extra = set(df.columns) - set(USER_FEATURE_COLUMNS)
    if extra:
        raise ValueError(f"Extra user feature columns: {extra}")


def validate_item_features(df):
    """
    Validate item features DataFrame against schema.
    
    Args:
        df: Item features DataFrame
    
    Raises:
        ValueError: If schema validation fails
    """
    missing = set(ITEM_FEATURE_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"Missing item feature columns: {missing}")
    
    extra = set(df.columns) - set(ITEM_FEATURE_COLUMNS)
    if extra:
        raise ValueError(f"Extra item feature columns: {extra}")


def validate_interaction_features(df):
    """
    Validate interaction features DataFrame against schema.
    
    Args:
        df: Interaction features DataFrame
    
    Raises:
        ValueError: If schema validation fails
    """
    missing = set(INTERACTION_FEATURE_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"Missing interaction feature columns: {missing}")
    
    extra = set(df.columns) - set(INTERACTION_FEATURE_COLUMNS)
    if extra:
        raise ValueError(f"Extra interaction feature columns: {extra}")
