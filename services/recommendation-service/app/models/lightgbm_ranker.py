"""
LightGBM Ranker Model Loader.

Why LightGBM:
- Trained in Phase 1 for learning-to-rank
- Fast inference (<10ms for 100 candidates)
- Handles missing features gracefully

Model expects features:
- User features (if available)
- Item features (always available)
- Interaction features (if user-item pair seen before)
"""
import lightgbm as lgb
from pathlib import Path
from typing import Optional, List
import numpy as np
import pandas as pd

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class LightGBMRanker:
    """
    LightGBM ranker for scoring candidates.
    
    Production considerations:
    - Lazy loading (model loaded on first prediction, not at startup)
    - Thread-safe (model is read-only after loading)
    - Graceful fallback if model file missing
    """
    
    def __init__(self):
        self.model: Optional[lgb.Booster] = None
        self.model_path = Path(settings.artifacts_path) / "models" / "lightgbm_ranker.txt"
        self.feature_names: Optional[List[str]] = None
    
    def load(self):
        """
        Load LightGBM model from disk.
        
        Why lazy loading:
        - Faster service startup (model loads on first request)
        - Allows service to start even if model file temporarily unavailable
        """
        if self.model is not None:
            return  # Already loaded
        
        try:
            logger.info(f"Loading LightGBM model from {self.model_path}")
            self.model = lgb.Booster(model_file=str(self.model_path))
            self.feature_names = self.model.feature_name()
            logger.info(f"LightGBM model loaded successfully | features={len(self.feature_names)}")
        except Exception as e:
            logger.error(f"Failed to load LightGBM model: {e}")
            self.model = None
            raise
    
    def predict(self, features_df: pd.DataFrame) -> np.ndarray:
        """
        Score candidates using LightGBM.
        
        Args:
            features_df: DataFrame with columns matching model.feature_name()
        
        Returns:
            Array of scores (higher = better)
        
        Why DataFrame input:
        - LightGBM handles missing values automatically
        - Feature order doesn't matter (uses column names)
        - Easy to debug (can inspect features_df)
        """
        if self.model is None:
            self.load()
        
        try:
            # Align features to model expectations
            # Missing features will be handled as NaN (LightGBM default)
            aligned_features = features_df.reindex(columns=self.feature_names, fill_value=np.nan)
            
            scores = self.model.predict(aligned_features)
            logger.debug(f"LightGBM scored {len(scores)} candidates | mean_score={scores.mean():.4f}")
            return scores
        
        except Exception as e:
            logger.error(f"LightGBM prediction failed: {e}")
            # Fallback: return uniform scores (caller will use popularity fallback)
            return np.zeros(len(features_df))
    
    def is_available(self) -> bool:
        """Check if model is loaded and ready."""
        return self.model is not None


# Global instance (singleton pattern)
_ranker_instance: Optional[LightGBMRanker] = None


def get_ranker() -> LightGBMRanker:
    """Get or create global LightGBM ranker instance."""
    global _ranker_instance
    if _ranker_instance is None:
        _ranker_instance = LightGBMRanker()
    return _ranker_instance


def get_ranker() -> LightGBMRanker:
    """
    Get or create global LightGBM ranker instance.
    
    Why singleton:
    - Model loaded once, shared across requests
    - Thread-safe (read-only after loading)
    - Memory efficient (model is ~50MB)
    """
    global _ranker_instance
    if _ranker_instance is None:
        _ranker_instance = LightGBMRanker()
    return _ranker_instance
