"""
Feature engineering module for Atlas recommendation system.

This module provides deterministic, reproducible feature computation
functions shared between training and serving.

Usage:
    from services.shared.features import (
        get_reference_time,
        compute_user_features,
        compute_item_features,
        compute_interaction_features
    )
"""
from .reference_time import get_reference_time
from .user_features import compute_user_features
from .item_features import compute_item_features
from .interaction_features import compute_interaction_features
from .schema import (
    USER_FEATURE_COLUMNS,
    ITEM_FEATURE_COLUMNS,
    INTERACTION_FEATURE_COLUMNS
)

__all__ = [
    'get_reference_time',
    'compute_user_features',
    'compute_item_features',
    'compute_interaction_features',
    'USER_FEATURE_COLUMNS',
    'ITEM_FEATURE_COLUMNS',
    'INTERACTION_FEATURE_COLUMNS',
]
