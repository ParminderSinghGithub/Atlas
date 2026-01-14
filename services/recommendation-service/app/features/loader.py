"""
Feature Loader for ML models.

Why separate feature loading:
- Features computed offline (Phase 1)
- Stored as Parquet (efficient columnar format)
- Loaded once at startup, cached in memory
- Optional Redis for distributed caching

Feature types:
1. User features: Demographics, behavior stats (if user known)
2. Item features: Category, price, popularity (always available)
3. Interaction features: User-item co-occurrence stats (if pair seen before)
"""
from pathlib import Path
from typing import Optional, Dict, Any
import pandas as pd
import numpy as np

from app.core.config import settings
from app.core.logging import get_logger, log_cache_miss

logger = get_logger(__name__)


class FeatureLoader:
    """
    Load and cache ML features from Parquet files.
    
    Production considerations:
    - Features loaded at startup (not lazy)
    - In-memory cache (DataFrame indexed by ID)
    - Missing features handled gracefully (return defaults)
    """
    
    def __init__(self):
        self.artifacts_path = Path(settings.artifacts_path)
        
        # Feature DataFrames (indexed by ID for fast lookup)
        self.user_features: Optional[pd.DataFrame] = None
        self.item_features: Optional[pd.DataFrame] = None
        self.interaction_features: Optional[pd.DataFrame] = None
        
        # Feature columns (for validation)
        self.user_feature_cols: list = []
        self.item_feature_cols: list = []
        self.interaction_feature_cols: list = []
    
    def load_all(self):
        """
        Load all feature tables from Parquet.
        
        Why at startup:
        - Predictable memory usage
        - Fast lookups during serving
        - Fails fast if files missing
        """
        logger.info("Loading feature tables from Parquet...")
        
        try:
            # Load user features
            user_path = self.artifacts_path / "features" / "retailrocket" / "user_features.parquet"
            if user_path.exists():
                self.user_features = pd.read_parquet(user_path)
                self.user_features.set_index('user_id', inplace=True)
                self.user_feature_cols = [c for c in self.user_features.columns if c != 'user_id']
                logger.info(f"Loaded user features | rows={len(self.user_features)} | cols={len(self.user_feature_cols)}")
            else:
                logger.warning(f"User features not found at {user_path}")
            
            # Load item features
            item_path = self.artifacts_path / "features" / "retailrocket" / "item_features.parquet"
            if item_path.exists():
                self.item_features = pd.read_parquet(item_path)
                # Handle column name variations (item_id or product_id)
                if 'product_id' in self.item_features.columns:
                    self.item_features.set_index('product_id', inplace=True)
                elif 'item_id' in self.item_features.columns:
                    self.item_features.set_index('item_id', inplace=True)
                else:
                    logger.error("Item features missing 'item_id' or 'product_id' column")
                    raise ValueError("Item features must have 'item_id' or 'product_id' column")
                
                self.item_feature_cols = [c for c in self.item_features.columns]
                logger.info(f"Loaded item features | rows={len(self.item_features)} | cols={len(self.item_feature_cols)}")
            else:
                logger.warning(f"Item features not found at {item_path}")
            
            # Load interaction features (optional)
            # SKIP: Too large (49MB), causes pod crashes during startup
            # Can be loaded lazily if needed in future
            interaction_path = self.artifacts_path / "features" / "retailrocket" / "interaction_features.parquet"
            if interaction_path.exists():
                logger.info(f"SKIP: Interaction features found at {interaction_path} but skipped (too large for startup)")
                # self.interaction_features = pd.read_parquet(interaction_path)
                # ... (rest of loading code commented out)
            else:
                logger.info(f"Interaction features not found at {interaction_path} (optional)")
        
        except Exception as e:
            logger.error(f"Failed to load feature tables: {e}")
            raise
    
    def get_user_features(self, user_id: str) -> Dict[str, Any]:
        """
        Get features for a user.
        
        Args:
            user_id: User identifier
        
        Returns:
            Dict of feature_name → value, or empty dict if user unknown
        
        Why dict not DataFrame:
        - Single user → single row lookup
        - Dict easier to merge with item features
        - Explicit handling of missing users
        """
        if self.user_features is None:
            return {}
        
        try:
            if user_id in self.user_features.index:
                return self.user_features.loc[user_id].to_dict()
            else:
                log_cache_miss(logger, f"user_features:{user_id}")
                return {}
        except Exception as e:
            logger.error(f"Error fetching user features for {user_id}: {e}")
            return {}
    
    def get_item_features(self, retailrocket_item_id: int) -> Dict[str, Any]:
        """
        Get features for an item.
        
        Args:
            retailrocket_item_id: RetailRocket item ID (NOT catalog UUID)
        
        Returns:
            Dict of feature_name → value, or defaults if item unknown
        
        Why return defaults vs empty:
        - Item features used in ranking (required)
        - LightGBM handles NaN but prefers defaults
        - Safer than missing features
        """
        if self.item_features is None:
            return self._get_default_item_features()
        
        try:
            if retailrocket_item_id in self.item_features.index:
                return self.item_features.loc[retailrocket_item_id].to_dict()
            else:
                log_cache_miss(logger, f"item_features:{retailrocket_item_id}")
                return self._get_default_item_features()
        except Exception as e:
            logger.error(f"Error fetching item features for {retailrocket_item_id}: {e}")
            return self._get_default_item_features()
    
    def get_interaction_features(self, user_id: str, retailrocket_item_id: int) -> Dict[str, Any]:
        """
        Get features for a user-item interaction.
        
        Returns:
            Dict of feature_name → value, or empty if no prior interaction
        
        Why optional:
        - Only exists for user-item pairs seen in training
        - Improves ranking for repeat interactions
        - Not required for cold start
        """
        if self.interaction_features is None:
            return {}
        
        try:
            key = (user_id, retailrocket_item_id)
            if key in self.interaction_features.index:
                return self.interaction_features.loc[key].to_dict()
            else:
                return {}
        except Exception as e:
            logger.error(f"Error fetching interaction features for ({user_id}, {retailrocket_item_id}): {e}")
            return {}
    
    def assemble_features(
        self, 
        user_id: Optional[str], 
        retailrocket_item_ids: list
    ) -> pd.DataFrame:
        """
        Assemble feature matrix for ranking.
        
        Args:
            user_id: User identifier (None for product-based recs)
            retailrocket_item_ids: List of candidate item IDs
        
        Returns:
            DataFrame with rows=items, columns=features
        
        Why DataFrame:
        - LightGBM expects DataFrame with named columns
        - Easy to align features with model expectations
        - Vectorized operations (faster than loops)
        """
        features_list = []
        
        # Get user features once (reused for all items)
        user_feats = self.get_user_features(user_id) if user_id else {}
        
        for item_id in retailrocket_item_ids:
            # Item features (required)
            item_feats = self.get_item_features(item_id)
            
            # Interaction features (optional)
            interaction_feats = self.get_interaction_features(user_id, item_id) if user_id else {}
            
            # Merge all features
            row_features = {
                **user_feats,
                **item_feats,
                **interaction_feats,
                'item_id': item_id  # Keep for debugging
            }
            features_list.append(row_features)
        
        features_df = pd.DataFrame(features_list)
        logger.debug(f"Assembled features for {len(features_df)} candidates | cols={len(features_df.columns)}")
        return features_df
    
    def _get_default_item_features(self) -> Dict[str, Any]:
        """
        Default item features for unknown items.
        
        Why defaults:
        - LightGBM prefers imputed values over NaN
        - Median/mode from training data would be better
        - For now, safe neutral values
        """
        return {
            'popularity_score': 0.0,
            'price': 0.0,
            'category_id': 0,
            'view_count': 0,
            'purchase_count': 0
        }


# Global instance
_loader_instance: Optional[FeatureLoader] = None


def get_feature_loader() -> FeatureLoader:
    """Get or create global feature loader instance."""
    global _loader_instance
    if _loader_instance is None:
        _loader_instance = FeatureLoader()
        _loader_instance.load_all()  # Load at startup
    return _loader_instance
