"""
SVD Matrix Factorization Model Loader for External ML Inference Service.
"""
import pickle
from pathlib import Path
from typing import Optional, List
import numpy as np

from ml_app.core.config import settings, resolve_model_path
from ml_app.core.logging import get_logger

logger = get_logger(__name__)


class SVDModel:
    """
    SVD collaborative filtering model loader & candidate generator.
    """

    def __init__(self):
        self.model = None
        self.model_path = resolve_model_path("svd_model.pkl")
        self.user_mapping: dict = {}
        self.item_mapping: dict = {}
        self.index_to_item: dict = {}
        self.user_factors: Optional[np.ndarray] = None
        self.item_factors: Optional[np.ndarray] = None

    def load(self) -> bool:
        """
        Load SVD model artifacts from disk.
        """
        if self.model is not None:
            return True

        if not self.model_path.exists():
            logger.warning("SVD model artifact not found at %s", self.model_path)
            return False

        try:
            logger.info("Loading SVD model from %s", self.model_path)
            with open(self.model_path, "rb") as f:
                artifact = pickle.load(f)

            self.model = artifact.get("model")
            self.user_factors = artifact.get("user_factors")
            self.item_factors = artifact.get("item_factors")

            # Extract user & item mappings (supports both naming variants)
            self.user_mapping = artifact.get("user_id_to_idx", artifact.get("user_id_to_index", {}))
            self.item_mapping = artifact.get("product_id_to_idx", artifact.get("index_to_item_id", {}))

            self.index_to_item = {idx: item_id for item_id, idx in self.item_mapping.items()}

            logger.info(
                "SVD model loaded successfully | users=%d | items=%d | factors=%s",
                len(self.user_mapping),
                len(self.item_mapping),
                self.user_factors.shape[1] if self.user_factors is not None else "N/A",
            )
            return True

        except Exception as exc:
            logger.exception("Failed to load SVD model from %s: %s", self.model_path, exc)
            self.model = None
            return False

    def is_available(self) -> bool:
        """Check if SVD model is loaded and ready."""
        return self.user_factors is not None and self.item_factors is not None

    def get_candidates(self, user_id: str, k: int = 100) -> Optional[List[int]]:
        """
        Generate top-K candidate items for a user.
        
        Returns:
            List of RetailRocket item IDs, or None if user is cold-start.
        """
        if not self.is_available():
            return None

        # Look up user index in matrix
        user_id_str = str(user_id)
        if user_id_str not in self.user_mapping:
            # Try integer lookup if user_id is numeric string
            if user_id_str.isdigit() and int(user_id_str) in self.user_mapping:
                user_idx = self.user_mapping[int(user_id_str)]
            else:
                return None
        else:
            user_idx = self.user_mapping[user_id_str]

        try:
            user_vector = self.user_factors[user_idx, :]
            scores = self.item_factors @ user_vector
            top_k_indices = np.argsort(scores)[::-1][:k]
            return [self.index_to_item[idx] for idx in top_k_indices if idx in self.index_to_item]
        except Exception as exc:
            logger.exception("Error generating SVD candidates for user %s: %s", user_id, exc)
            return None


_svd_instance: Optional[SVDModel] = None


def get_svd_model() -> SVDModel:
    """Singleton getter for SVD model."""
    global _svd_instance
    if _svd_instance is None:
        _svd_instance = SVDModel()
    return _svd_instance
