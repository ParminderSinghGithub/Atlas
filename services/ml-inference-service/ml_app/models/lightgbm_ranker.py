"""
LightGBM Ranker Model Loader for External ML Inference Service.
"""
from pathlib import Path
from typing import Optional, List
import numpy as np
import pandas as pd

try:
    import lightgbm as lgb
except ImportError:
    lgb = None

from ml_app.core.config import settings, resolve_model_path
from ml_app.core.logging import get_logger

logger = get_logger(__name__)


class LightGBMRanker:
    """
    LightGBM Ranker model for Stage-2 candidate scoring.
    """

    def __init__(self):
        self.model: Optional[lgb.Booster] = None
        self.model_path = resolve_model_path("lightgbm_ranker.txt")
        self.feature_names: Optional[List[str]] = None

    def load(self) -> bool:
        """Load LightGBM model from text model file."""
        if self.model is not None:
            return True

        if lgb is None:
            logger.warning("lightgbm package is not installed; ranking disabled")
            return False

        if not self.model_path.exists():
            logger.warning("LightGBM model artifact not found at %s", self.model_path)
            return False

        try:
            logger.info("Loading LightGBM ranker from %s", self.model_path)
            self.model = lgb.Booster(model_file=str(self.model_path))
            self.feature_names = self.model.feature_name()
            logger.info(
                "LightGBM ranker loaded successfully | features=%d",
                len(self.feature_names) if self.feature_names else 0,
            )
            return True
        except Exception as exc:
            logger.exception("Failed to load LightGBM model from %s: %s", self.model_path, exc)
            self.model = None
            return False

    def is_available(self) -> bool:
        """Check if model is loaded and ready."""
        return self.model is not None

    def predict(self, features_df: pd.DataFrame) -> np.ndarray:
        """
        Score candidate feature matrix using LightGBM.
        
        Args:
            features_df: DataFrame with feature columns
            
        Returns:
            np.ndarray of float scores
        """
        if not self.is_available():
            if not self.load():
                return np.zeros(len(features_df))

        try:
            aligned_features = features_df.reindex(columns=self.feature_names, fill_value=np.nan)
            scores = self.model.predict(aligned_features)
            return np.asarray(scores, dtype=float)
        except Exception as exc:
            logger.exception("LightGBM scoring failed: %s", exc)
            return np.zeros(len(features_df))


_ranker_instance: Optional[LightGBMRanker] = None


def get_ranker() -> LightGBMRanker:
    """Singleton getter for LightGBM ranker."""
    global _ranker_instance
    if _ranker_instance is None:
        _ranker_instance = LightGBMRanker()
    return _ranker_instance
