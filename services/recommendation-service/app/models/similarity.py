"""
Item-Item Similarity Model Loader.

Why item-item similarity:
- Product-based recommendations (users browsing a specific item)
- Cold start for new users (no history yet)
- Complementary products ("customers who bought X also bought Y")

Model outputs RetailRocket latent item IDs (must be mapped to catalog UUIDs).
"""
import pickle
from pathlib import Path
from typing import Optional, List, Dict
import numpy as np

from app.core.config import settings, get_model_path
from app.core.logging import get_logger

logger = get_logger(__name__)


class SimilarityModel:
    """
    Item-item similarity for product-based recommendations.
    
    Production considerations:
    - Precomputed similarity dict from Phase 1 (sparse format)
    - Fast lookup (<5ms for top-100 similar items)
    - Falls back to popularity if item not in similarity dict
    """
    
    def __init__(self):
        self.similarity_dict: Optional[Dict[str, Dict[str, float]]] = None
        self.model_path = get_model_path("item_similarity.pkl")
    
    def load(self):
        """
        Load item-item similarity dictionary.
        
        Artifact contains:
        - similarity: Dict[item_id_str, Dict[similar_item_id_str, score]]
        - item_counts: Item interaction counts
        - created_at: Timestamp
        
        Format: Sparse dictionary for memory efficiency
        """
        if self.similarity_dict is not None:
            return  # Already loaded
        
        try:
            logger.info(f"Loading item-item similarity from {self.model_path}")
            with open(self.model_path, 'rb') as f:
                artifact = pickle.load(f)
            
            # Extract similarity dictionary (sparse format)
            self.similarity_dict = artifact.get('similarity', {})
            
            if not self.similarity_dict:
                logger.warning("Similarity dict is empty!")
                raise ValueError("Loaded similarity dict is empty")
            
            # Count total similarities
            total_similarities = sum(len(similar_items) for similar_items in self.similarity_dict.values())
            
            logger.info(
                f"Similarity model loaded | "
                f"items={len(self.similarity_dict)} | "
                f"total_similarities={total_similarities}"
            )
        
        except Exception as e:
            logger.error(f"Failed to load similarity model: {e}")
            self.similarity_dict = None
            raise
    
    def get_similar_items(self, item_id: int, k: int = 100) -> Optional[List[int]]:
        """
        Get top-K similar items for given item.
        
        Args:
            item_id: RetailRocket item ID (int)
            k: Number of similar items to return
        
        Returns:
            List of RetailRocket item IDs, or None if item unknown
        
        Why return None for unknown items:
        - Explicit signal to caller
        - Allows fallback to category popularity
        - More honest than returning random items
        """
        if self.similarity_dict is None:
            self.load()
        
        # Convert item_id to string (similarity dict uses string keys)
        item_id_str = str(item_id)
        
        # Check if item exists in similarity dict
        if item_id_str not in self.similarity_dict:
            logger.debug(f"Item {item_id} not in similarity dict")
            return None
        
        try:
            # Get similar items dictionary for this item
            similar_items_dict = self.similarity_dict[item_id_str]
            
            if not similar_items_dict:
                logger.debug(f"No similar items found for item {item_id}")
                return None
            
            # Sort by similarity score (descending) and take top-K
            sorted_items = sorted(
                similar_items_dict.items(),
                key=lambda x: x[1],  # Sort by score
                reverse=True
            )[:k]
            
            # Extract item IDs (convert back to int)
            similar_items = [int(item_id_str) for item_id_str, score in sorted_items]
            
            logger.debug(f"Found {len(similar_items)} similar items for item {item_id}")
            return similar_items
        
        except Exception as e:
            logger.error(f"Similarity lookup failed for item {item_id}: {e}")
            return None
    
    def is_available(self) -> bool:
        """Check if model is loaded and ready."""
        return self.similarity_dict is not None


# Global instance
_similarity_instance: Optional[SimilarityModel] = None


def get_similarity_model() -> SimilarityModel:
    """Get or create global similarity model instance."""
    global _similarity_instance
    if _similarity_instance is None:
        _similarity_instance = SimilarityModel()
    return _similarity_instance
