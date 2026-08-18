"""
Item-Item Similarity Model Loader for External ML Inference Service.
"""
import pickle
from pathlib import Path
from typing import Optional, List, Dict

from ml_app.core.config import settings, resolve_model_path
from ml_app.core.logging import get_logger

logger = get_logger(__name__)


class SimilarityModel:
    """
    Item-item similarity model for product-based candidate generation.
    """

    def __init__(self):
        self.similarity_dict: Optional[Dict[str, Dict[str, float]]] = None
        self.model_path = resolve_model_path("item_similarity.pkl")

    def load(self) -> bool:
        """Load item similarity dictionary from pickle artifact."""
        if self.similarity_dict is not None:
            return True

        if not self.model_path.exists():
            logger.warning("Similarity artifact not found at %s", self.model_path)
            return False

        try:
            logger.info("Loading item similarity from %s", self.model_path)
            with open(self.model_path, "rb") as f:
                artifact = pickle.load(f)

            self.similarity_dict = artifact.get("similarity", {})
            if not self.similarity_dict:
                logger.warning("Similarity dictionary is empty in %s", self.model_path)
                return False

            total_pairs = sum(len(neighbors) for neighbors in self.similarity_dict.values())
            logger.info(
                "Similarity model loaded successfully | items=%d | total_pairs=%d",
                len(self.similarity_dict),
                total_pairs,
            )
            return True

        except Exception as exc:
            logger.exception("Failed to load similarity model from %s: %s", self.model_path, exc)
            self.similarity_dict = None
            return False

    def is_available(self) -> bool:
        """Check if similarity dictionary is loaded."""
        return self.similarity_dict is not None and len(self.similarity_dict) > 0

    def get_similar_items(self, item_id: int, k: int = 100) -> Optional[List[int]]:
        """
        Get top-K similar items for a given item ID.
        
        Returns:
            List of RetailRocket item IDs, or None if item is unknown.
        """
        if not self.is_available():
            return None

        # Check str and int keys
        key = str(item_id)
        if key not in self.similarity_dict:
            if item_id in self.similarity_dict:
                similar_items_dict = self.similarity_dict[item_id]
            else:
                return None
        else:
            similar_items_dict = self.similarity_dict[key]

        try:
            # Sort by similarity score descending
            sorted_items = sorted(
                similar_items_dict.items(),
                key=lambda x: x[1],
                reverse=True
            )[:k]

            return [int(item[0]) for item in sorted_items]
        except Exception as exc:
            logger.exception("Error extracting similar items for %s: %s", item_id, exc)
            return None


_similarity_instance: Optional[SimilarityModel] = None


def get_similarity_model() -> SimilarityModel:
    """Singleton getter for similarity model."""
    global _similarity_instance
    if _similarity_instance is None:
        _similarity_instance = SimilarityModel()
    return _similarity_instance
