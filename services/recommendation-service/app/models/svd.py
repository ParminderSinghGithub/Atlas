"""
SVD (Matrix Factorization) Model Loader.

Why SVD:
- Collaborative filtering for user-based recommendations
- Trained on user-item interaction matrix in Phase 1
- Fast candidate generation (<5ms for top-100)

Model outputs RetailRocket latent item IDs (must be mapped to catalog UUIDs).

IMPORTANT LIMITATION:
- Trained on RetailRocket users (integer user IDs)
- New application users (UUID format) will NOT be in model
- Expected cold start: ALL new app users fall back to popularity baseline
- This is CORRECT BEHAVIOR - no fake personalization
"""
import pickle
from pathlib import Path
from typing import Optional, List
import numpy as np

from app.core.config import settings, get_model_path
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
        self.model_path = get_model_path("svd_model.pkl")
        self.user_mapping: Optional[dict] = None  # user_id → index
        self.item_mapping: Optional[dict] = None  # item_id → index
        self.index_to_item: Optional[dict] = None  # index → item_id (reverse mapping)
        self.user_factors: Optional[np.ndarray] = None  # (n_users, n_factors)
        self.item_factors: Optional[np.ndarray] = None  # (n_items, n_factors)
    
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
            
            # Extract model and latent factors
            self.model = artifact['model']  # sklearn TruncatedSVD
            self.user_factors = artifact.get('user_factors')  # Shape: (n_users, n_factors)
            self.item_factors = artifact.get('item_factors')  # Shape: (n_items, n_factors)
            
            # Extract ID mappings (NOTE: pickle uses different key names than expected!)
            self.user_mapping = artifact.get('user_id_to_idx', artifact.get('user_id_to_index', {}))
            self.item_mapping = artifact.get('product_id_to_idx', artifact.get('index_to_item_id', {}))
            
            # Create reverse mapping: index → item_id for candidate generation
            self.index_to_item = {idx: item_id for item_id, idx in self.item_mapping.items()}
            
            logger.info(
                f"SVD model loaded | "
                f"users={len(self.user_mapping)} | "
                f"items={len(self.item_mapping)} | "
                f"factors={self.user_factors.shape[1] if self.user_factors is not None else 'N/A'}"
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
            # Convert user_id to string (mappings use string keys)
            user_id_str = str(user_id)
            
            if user_id_str not in self.user_mapping:
                logger.debug(f"User {user_id} not in SVD mapping")
                return None
            
            user_idx = self.user_mapping[user_id_str]
            
            # Get user's latent factor vector (shape: (n_factors,))
            user_vector = self.user_factors[user_idx, :]
            
            # Compute scores for ALL items: score = user_vector · item_vector^T
            # user_vector: (n_factors,)
            # item_factors: (n_items, n_factors)
            # scores: (n_items,)
            scores = self.item_factors @ user_vector
            
            # Get top-K item indices (highest scores)
            top_k_indices = np.argsort(scores)[::-1][:k]
            
            # Map indices to RetailRocket item IDs
            retailrocket_ids = [
                self.index_to_item[idx] 
                for idx in top_k_indices 
                if idx in self.index_to_item
            ]
            
            logger.info(f"SVD generated {len(retailrocket_ids)} candidates for user {user_id} | mean_score={scores[top_k_indices].mean():.4f}")
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
