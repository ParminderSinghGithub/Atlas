"""
Reference time computation for feature engineering.

All features are computed relative to a reference time to prevent data leakage.
In production, this would be the current timestamp. For training, we use the
latest event timestamp.
"""
from typing import Optional
import pandas as pd


def get_reference_time(
    events_df: pd.DataFrame,
    explicit_reference_time: Optional[pd.Timestamp] = None
) -> pd.Timestamp:
    """
    Get reference time for feature computation.
    
    Args:
        events_df: DataFrame with 'ts_datetime' column
        explicit_reference_time: Optional explicit reference time.
                                 If provided, this is returned as-is.
    
    Returns:
        Reference timestamp for feature computation
    
    Why explicit_reference_time parameter:
    - Training: Use max(ts_datetime) from training data
    - Retraining: May want to use a specific cutoff time
    - Production: Would use current timestamp (not from events)
    
    Examples:
        # Training: infer from data
        reference_time = get_reference_time(events_df)
        
        # Retraining with fixed cutoff
        reference_time = get_reference_time(
            events_df,
            explicit_reference_time=pd.Timestamp('2026-01-01', tz='UTC')
        )
    """
    if explicit_reference_time is not None:
        return explicit_reference_time
    
    # Infer from data: use latest event timestamp
    if 'ts_datetime' not in events_df.columns:
        raise ValueError("events_df must have 'ts_datetime' column")
    
    return events_df['ts_datetime'].max()
