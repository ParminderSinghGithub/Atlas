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

from app.core.config import settings
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
        self.model_path = Path(settings.artifacts_path) / "models" / "popularity_baseline.pkl"
    
    def load(self):
        """
        Load popularity scores.
        
        Artifact format:
        - pd.Series with index=retailrocket_item_id, values=popularity_score
        - Sorted by score descending
        
        Fallback: If popularity_baseline.pkl missing, generate from item_features.parquet
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
                logger.warning("No popularity proxy column found in item_features, using uniform scores")
                # Use product_id or item_id as index
                id_col = 'product_id' if 'product_id' in item_features.columns else 'item_id'
                self.popularity_scores = pd.Series(
                    data=1.0,
                    index=item_features[id_col] if id_col in item_features.columns else item_features.index
                )
                return
            
            # Create popularity series
            id_col = 'product_id' if 'product_id' in item_features.columns else 'item_id'
            if id_col in item_features.columns:
                self.popularity_scores = item_features.set_index(id_col)[popularity_col]
            else:
                self.popularity_scores = item_features[popularity_col]
            
            # Sort descending
            self.popularity_scores = self.popularity_scores.sort_values(ascending=False)
            
            logger.info(f"Generated popularity from item_features | items={len(self.popularity_scores)} | proxy={popularity_col}")
        
        except Exception as e:
            logger.error(f"Failed to generate popularity from item_features: {e}")
            # Ultimate fallback: empty series
            self.popularity_scores = pd.Series(dtype=float)
        
        except Exception as e:
            logger.error(f"Failed to load popularity baseline: {e}")
            self.popularity_scores = None
            raise
    
    def get_top_k(self, k: int = 20) -> List[int]:
        """
        Get top-K most popular items.
        
        Args:
            k: Number of items to return
        
        Returns:
            List of RetailRocket item IDs (sorted by popularity)
        
        Why always succeed:
        - This is the last-resort fallback
        - If this fails, service is unusable
        - Better to return something than nothing
        """
        if self.popularity_scores is None:
            self.load()
        
        try:
            # Get top-K item IDs
            top_k_ids = self.popularity_scores.head(k).index.tolist()
            logger.debug(f"Popularity baseline returned {len(top_k_ids)} items")
            return top_k_ids
        
        except Exception as e:
            logger.error(f"Popularity baseline failed: {e}")
            # Ultimate fallback: return empty list (caller must handle)
            return []
    
    def get_score(self, retailrocket_item_id: int) -> float:
        """
        Get popularity score for a specific item.
        
        Why needed:
        - Tie-breaking in ranking
        - Fallback scoring when LightGBM unavailable
        """
        if self.popularity_scores is None:
            self.load()
        
        return self.popularity_scores.get(retailrocket_item_id, 0.0)
    
    def is_available(self) -> bool:
        """Check if model is loaded and ready."""
        return self.popularity_scores is not None


# Global instance
_popularity_instance: Optional[PopularityModel] = None


def get_popularity_model() -> PopularityModel:
    """Get or create global popularity model instance."""
    global _popularity_instance
    if _popularity_instance is None:
        _popularity_instance = PopularityModel()
    return _popularity_instance
