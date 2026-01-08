"""
Popularity Baseline Model.

Why popularity baseline:
- Cold start fallback (unknown users/products)
- Simple, explainable, always available
- Trained on interaction counts in Phase 1

Returns RetailRocket item IDs (must be mapped to catalog UUIDs).
"""
import pickle
from pathlib import Path
from typing import Optional, List
import pandas as pd

from app.core.config import settings, get_model_path
from app.core.logging import get_logger

logger = get_logger(__name__)


class PopularityModel:
    """
    Popularity-based recommendations.
    
    Why popularity:
    - Never fails (always returns results)
    - Good cold start performance
    - Computationally trivial
    
    Production considerations:
    - Can be updated daily without retraining
    - Should reflect recent trends (e.g., 30-day window)
    - Category-aware popularity improves relevance
    """
    
    def __init__(self):
        self.popularity_scores: Optional[pd.Series] = None
        self.model_path = get_model_path("popularity_baseline.pkl")
    
    def load(self):
        """
        Load popularity scores.
        
        Artifact format:
        - pd.Series with index=retailrocket_item_id, values=popularity_score
        - Sorted by score descending
        
        Fallback: If popularity_scores.pkl missing, generate from item_features.parquet
        """
        if self.popularity_scores is not None:
            return  # Already loaded
        
        try:
            logger.info(f"Loading popularity baseline from {self.model_path}")
            with open(self.model_path, 'rb') as f:
                self.popularity_scores = pickle.load(f)
            
            # Ensure sorted descending
            self.popularity_scores = self.popularity_scores.sort_values(ascending=False)
            
            logger.info(f"Popularity baseline loaded | items={len(self.popularity_scores)}")
        
        except FileNotFoundError:
            logger.warning(f"Popularity baseline not found at {self.model_path}, generating from item_features")
            self._generate_from_item_features()
        
        except Exception as e:
            logger.error(f"Failed to load popularity baseline: {e}")
            raise
    
    def _generate_from_item_features(self):
        """
        Generate popularity baseline from item_features.parquet.
        
        Why fallback:
        - popularity_baseline.pkl may not exist yet
        - Can compute from item interaction counts
        - Better than failing to start
        """
        try:
            features_path = Path(settings.artifacts_path) / "features" / "retailrocket" / "item_features.parquet"
            if not features_path.exists():
                logger.error(f"Item features not found at {features_path}")
                # Ultimate fallback: empty series
                self.popularity_scores = pd.Series(dtype=float)
                return
            
            item_features = pd.read_parquet(features_path)
            
            # Use view_count or interaction count as popularity proxy
            if 'total_views' in item_features.columns:
                popularity_col = 'total_views'
            elif 'view_count' in item_features.columns:
                popularity_col = 'view_count'
            elif 'interaction_count' in item_features.columns:
                popularity_col = 'interaction_count'
            elif 'purchase_count' in item_features.columns:
                popularity_col = 'purchase_count'
            elif 'popularity_score' in item_features.columns:
                popularity_col = 'popularity_score'
            else:
                # Ultimate fallback: uniform scores
                logger.warning("No popularity column found in item_features, using uniform scores")
                self.popularity_scores = pd.Series(data=1.0, index=range(len(item_features)))
                return
            
            # Determine ID column
            if 'product_id' in item_features.columns:
                id_col = 'product_id'
            elif 'item_id' in item_features.columns:
                id_col = 'item_id'
            else:
                # Use index as IDs
                id_col = None
            
            # Create popularity series
            if id_col:
                # Convert product_id to int for consistent typing with latent_item_id
                item_features_copy = item_features.copy()
                item_features_copy[id_col] = item_features_copy[id_col].astype(int)
                self.popularity_scores = (
                    item_features_copy
                    .set_index(id_col)[popularity_col]
                    .sort_values(ascending=False)
                )
                logger.info(f"Using {id_col} as index (converted to int) | min={self.popularity_scores.index.min()} | max={self.popularity_scores.index.max()}")
            else:
                self.popularity_scores = (
                    item_features[popularity_col]
                    .sort_values(ascending=False)
                )
            
            logger.info(f"Generated popularity baseline from item_features | items={len(self.popularity_scores)}")
        
        except Exception as e:
            logger.error(f"Failed to generate popularity baseline: {e}")
            self.popularity_scores = pd.Series(dtype=float)
    
    def get_top_k(self, k: int = 100, valid_ids: Optional[List[int]] = None) -> List[int]:
        """
        Get top-K popular items.
        
        Args:
            k: Number of items to return
            valid_ids: Optional list of valid item IDs to filter by (for catalog mapping)
        
        Returns:
            List of RetailRocket item IDs
        
        Why valid_ids filtering:
        - Popularity baseline has 235K items from retailrocket
        - Only ~2K items have catalog UUID mappings
        - Filter ensures we only recommend mapped items
        """
        if self.popularity_scores is None:
            self.load()
        
        if len(self.popularity_scores) == 0:
            logger.warning("Popularity scores empty")
            return []
        
        # Filter by valid IDs if provided
        scores_to_use = self.popularity_scores
        if valid_ids is not None:
            valid_set = set(valid_ids)
            scores_to_use = self.popularity_scores[self.popularity_scores.index.isin(valid_set)]
            logger.info(f"Filtered popularity to {len(scores_to_use)}/{len(self.popularity_scores)} valid mapped items")
            
            if len(scores_to_use) == 0:
                logger.warning("No valid mapped items in popularity baseline")
                return []
        
        # Return top-K item IDs
        top_items = scores_to_use.nlargest(min(k, len(scores_to_use)))
        return [int(item_id) for item_id in top_items.index]
    
    def is_available(self) -> bool:
        """Check if model is loaded and ready."""
        return self.popularity_scores is not None and len(self.popularity_scores) > 0


# Global instance
_popularity_instance: Optional[PopularityModel] = None


def get_popularity_model() -> PopularityModel:
    """Get or create global popularity model instance."""
    global _popularity_instance
    if _popularity_instance is None:
        _popularity_instance = PopularityModel()
    return _popularity_instance
