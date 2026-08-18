"""
Feature Loader for External ML Inference Service.
"""
from pathlib import Path
from typing import Optional, Dict, Any, List
import pandas as pd
import numpy as np

from ml_app.core.config import settings, resolve_feature_path
from ml_app.core.logging import get_logger

logger = get_logger(__name__)


class FeatureLoader:
    """
    Load, index, and assemble feature tables for LightGBM ranking.
    """

    def __init__(self):
        self.user_features: Optional[pd.DataFrame] = None
        self.item_features: Optional[pd.DataFrame] = None

        self.user_feature_cols: List[str] = []
        self.item_feature_cols: List[str] = []

    def load_all(self) -> bool:
        """
        Load user and item feature tables into memory.
        """
        try:
            user_path = resolve_feature_path("user_features.parquet")
            if user_path.exists():
                logger.info("Loading user features from %s", user_path)
                df_user = pd.read_parquet(user_path)
                if "user_id" in df_user.columns:
                    df_user["user_id"] = pd.to_numeric(df_user["user_id"], errors="coerce")
                    df_user.dropna(subset=["user_id"], inplace=True)
                    df_user["user_id"] = df_user["user_id"].astype(int)
                    df_user.set_index("user_id", inplace=True)

                self.user_features = df_user
                self.user_feature_cols = list(df_user.columns)
                logger.info("Loaded user features | rows=%d | cols=%d", len(df_user), len(self.user_feature_cols))
            else:
                logger.warning("User features parquet not found at %s", user_path)

            item_path = resolve_feature_path("item_features.parquet")
            if item_path.exists():
                logger.info("Loading item features from %s", item_path)
                df_item = pd.read_parquet(item_path)
                id_col = "product_id" if "product_id" in df_item.columns else ("item_id" if "item_id" in df_item.columns else None)
                if id_col:
                    df_item[id_col] = pd.to_numeric(df_item[id_col], errors="coerce")
                    df_item.dropna(subset=[id_col], inplace=True)
                    df_item[id_col] = df_item[id_col].astype(int)
                    df_item.set_index(id_col, inplace=True)

                self.item_features = df_item
                self.item_feature_cols = list(df_item.columns)
                logger.info("Loaded item features | rows=%d | cols=%d", len(df_item), len(self.item_feature_cols))
            else:
                logger.warning("Item features parquet not found at %s", item_path)

            return True

        except Exception as exc:
            logger.exception("Failed to load feature tables: %s", exc)
            return False

    def is_available(self) -> bool:
        """Check if feature tables are loaded."""
        return self.user_features is not None or self.item_features is not None

    def _normalize_key(self, value: Any) -> Optional[int]:
        """Convert key to int if possible."""
        try:
            if isinstance(value, str) and value.isdigit():
                return int(value)
            if isinstance(value, (int, np.integer)):
                return int(value)
        except (ValueError, TypeError):
            pass
        return None

    def get_user_features(self, user_id: Optional[str]) -> Dict[str, Any]:
        """Fetch user feature dict."""
        if self.user_features is None or user_id is None:
            return {}

        norm_id = self._normalize_key(user_id)
        if norm_id is not None and norm_id in self.user_features.index:
            return self.user_features.loc[norm_id].to_dict()

        return {}

    def get_item_features(self, item_id: int) -> Dict[str, Any]:
        """Fetch item feature dict with fallback defaults."""
        if self.item_features is not None:
            norm_id = self._normalize_key(item_id)
            if norm_id is not None and norm_id in self.item_features.index:
                return self.item_features.loc[norm_id].to_dict()

        return self._get_default_item_features()

    def assemble_features(
        self,
        user_id: Optional[str],
        retailrocket_item_ids: List[int],
    ) -> pd.DataFrame:
        """
        Assemble combined user+item feature matrix for candidates.
        """
        user_feats = self.get_user_features(user_id)
        rows = []

        for item_id in retailrocket_item_ids:
            item_feats = self.get_item_features(item_id)
            combined = {**user_feats, **item_feats, "item_id": item_id}
            rows.append(combined)

        return pd.DataFrame(rows)

    def _get_default_item_features(self) -> Dict[str, Any]:
        """Default feature values for unseen items."""
        return {
            "total_views": 0,
            "total_add_to_cart": 0,
            "total_purchases": 0,
            "popularity_score": 0.0,
            "conversion_rate": 0.0,
            "days_since_first_event": 0,
            "days_since_last_event": 999,
        }


_feature_loader_instance: Optional[FeatureLoader] = None


def get_feature_loader() -> FeatureLoader:
    """Singleton getter for FeatureLoader."""
    global _feature_loader_instance
    if _feature_loader_instance is None:
        _feature_loader_instance = FeatureLoader()
    return _feature_loader_instance
