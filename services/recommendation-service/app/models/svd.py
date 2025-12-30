"""
SVD (Matrix Factorization) Model Loader.

Why SVD:
- Collaborative filtering for user-based recommendations
- Trained on user-item interaction matrix in Phase 1
- Fast candidate generation (<5ms for top-100)

Model outputs RetailRocket latent item IDs (must be mapped to catalog UUIDs).
"""
import pickle
from pathlib import Path
from typing import Optional, List
import numpy as np

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class SVDModel:
    """
    Singular Value Decomposition model for collaborative filtering.
    
    Production considerations:
    - Outputs RetailRocket IDs (NOT catalog UUIDs)
    - Requires latent_item_mappings for translation
    - Cold start: returns None for unknown users
    """
    
    def __init__(self):
        self.model = None
        self.model_path = Path(settings.artifacts_path) / "models" / "svd_model.pkl"
        self.user_mapping: Optional[dict] = None  # user_id → model_index
        self.item_mapping: Optional[dict] = None  # model_index → retailrocket_item_id
    
    def load(self):
        """
        Load SVD model and mappings.
        
        Model artifact contains:
        - U: User latent factors
        - V: Item latent factors  
        - user_id_to_index: Mapping of user IDs to matrix rows
        - index_to_item_id: Mapping of matrix columns to RetailRocket item IDs
        """
        if self.model is not None:
            return  # Already loaded
        
        try:
            logger.info(f"Loading SVD model from {self.model_path}")
            with open(self.model_path, 'rb') as f:
                artifact = pickle.load(f)
            
            self.model = artifact['model']  # sklearn TruncatedSVD or similar
            self.user_mapping = artifact.get('user_id_to_index', {})
            self.item_mapping = artifact.get('index_to_item_id', {})
            
            logger.info(
                f"SVD model loaded | "
                f"users={len(self.user_mapping)} | "
                f"items={len(self.item_mapping)}"
            )
        
        except Exception as e:
            logger.error(f"Failed to load SVD model: {e}")
            self.model = None
            raise
    
    def get_candidates(self, user_id: str, k: int = 100) -> Optional[List[int]]:
        """
        Get top-K candidate items for user.
        
        Args:
            user_id: User identifier (string)
            k: Number of candidates to return
        
        Returns:
            List of RetailRocket item IDs, or None if user unknown
        
        Why return None for unknown users:
        - Explicit cold start signal
        - Caller can fallback to popularity baseline
        - More honest than returning random items
        """
        if self.model is None:
            self.load()
        
        # Check if user exists in training data
        if user_id not in self.user_mapping:
            logger.debug(f"User {user_id} not in SVD model (cold start)")
            return None
        
        try:
            user_idx = self.user_mapping[user_id]
            
            # Get user's latent vector
            # Compute scores for all items: score = user_vector · item_vectors
            user_vector = self.model.components_[user_idx]
            item_vectors = self.model.components_.T
            scores = item_vectors @ user_vector
            
            # Get top-K item indices
            top_k_indices = np.argsort(scores)[::-1][:k]
            
            # Map indices to RetailRocket item IDs
            retailrocket_ids = [
                self.item_mapping[idx] 
                for idx in top_k_indices 
                if idx in self.item_mapping
            ]
            
            logger.debug(f"SVD generated {len(retailrocket_ids)} candidates for user {user_id}")
            return retailrocket_ids
        
        except Exception as e:
            logger.error(f"SVD prediction failed for user {user_id}: {e}")
            return None
    
    def is_available(self) -> bool:
        """Check if model is loaded and ready."""
        return self.model is not None


# Global instance
_svd_instance: Optional[SVDModel] = None


def get_svd_model() -> SVDModel:
    """Get or create global SVD model instance."""
    global _svd_instance
    if _svd_instance is None:
        _svd_instance = SVDModel()
    return _svd_instance
