"""
Latent ID to Catalog UUID Mapping.

Critical bridge:
- ML models output RetailRocket IDs (integers 1-235061)
- Catalog API expects product UUIDs
- latent_item_mappings table provides translation

Why database query:
- Mapping is dynamic (new products can be added)
- Confidence scores filter low-quality mappings
- Allows A/B testing different mapping strategies
"""
from typing import List, Dict, Optional
from uuid import UUID
import asyncpg
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class LatentMapper:
    """
    Translates RetailRocket latent item IDs to catalog product UUIDs.
    
    Production considerations:
    - Async database queries (non-blocking)
    - Connection pooling (reuse connections)
    - Confidence threshold filtering
    - Handles missing mappings gracefully
    """
    
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None
    
    async def connect(self):
        """
        Create database connection pool.
        
        Why connection pool:
        - Reuse connections across requests (avoid handshake overhead)
        - Limit concurrent connections (prevent DB overload)
        - Automatic connection health checks
        """
        if self.pool is not None:
            return  # Already connected
        
        try:
            logger.info(f"Connecting to database for latent mappings...")
            self.pool = await asyncpg.create_pool(
                settings.database_url.replace('postgresql+asyncpg://', 'postgresql://'),
                min_size=2,
                max_size=10,
                command_timeout=5
            )
            logger.info("Database connection pool created")
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            raise
    
    async def map_to_catalog(
        self,
        retailrocket_item_ids: List[int],
        confidence_threshold: float = None,
        preserve_ids: bool = False
    ) -> List[UUID]:
        """
        Translate RetailRocket IDs to catalog UUIDs.
        
        Args:
            retailrocket_item_ids: List of RetailRocket item IDs (int or str convertible)
            confidence_threshold: Minimum confidence score (default from config)
            preserve_ids: If True, return list of tuples (UUID, retailrocket_id)
        
        Returns:
            List of catalog product UUIDs (may be shorter if some IDs unmapped)
            If preserve_ids=True: List of (UUID, retailrocket_id) tuples
        
        Why confidence threshold:
        - Low confidence = weak mapping (e.g., random assignment)
        - High confidence = strong mapping (e.g., same category + popularity)
        - Threshold filters noise
        """
        if self.pool is None:
            await self.connect()
        
        if not retailrocket_item_ids:
            return []
        
        # Convert string IDs to integers if needed
        try:
            int_ids = [int(id_) if isinstance(id_, str) else id_ for id_ in retailrocket_item_ids]
        except (ValueError, TypeError) as e:
            logger.error(f"Failed to convert IDs to integers: {e}")
            return []
        
        confidence_threshold = confidence_threshold or settings.confidence_threshold
        
        try:
            async with self.pool.acquire() as conn:
                # Query latent_item_mappings table
                query = """
                    SELECT product_id, latent_item_id, confidence_score
                    FROM latent_item_mappings
                    WHERE latent_item_id = ANY($1)
                      AND confidence_score >= $2
                    ORDER BY confidence_score DESC
                """
                logger.info(f"Querying mappings for {len(int_ids)} items | threshold={confidence_threshold}")
                logger.info(f"Sample IDs: {int_ids[:5]}")
                
                rows = await conn.fetch(query, int_ids, confidence_threshold)
                logger.info(f"Query returned {len(rows)} rows")
                
                # Extract UUIDs (preserve order from input for ranking consistency)
                uuid_map = {row['latent_item_id']: row['product_id'] for row in rows}
                logger.info(f"UUID map size: {len(uuid_map)}")
                
                if preserve_ids:
                    # Return tuples of (UUID, retailrocket_id) to preserve score mapping
                    catalog_results = [
                        (uuid_map[item_id], item_id)
                        for item_id in int_ids
                        if item_id in uuid_map
                    ]
                else:
                    # Return just UUIDs
                    catalog_results = [
                        uuid_map[item_id] 
                        for item_id in int_ids  # Use int_ids to match uuid_map keys
                        if item_id in uuid_map
                    ]
                
                logger.info(
                    f"Mapped {len(catalog_results)}/{len(int_ids)} items | "
                    f"confidence>={confidence_threshold}"
                )
                
                return catalog_results
        
        except Exception as e:
            logger.error(f"Latent mapping query failed: {e}")
            return []
    
    async def map_with_metadata(
        self,
        retailrocket_item_ids: List[int],
        confidence_threshold: float = None
    ) -> List[Dict]:
        """
        Translate with mapping metadata (for debugging/explainability).
        
        Returns:
            List of dicts with product_id, latent_item_id, confidence_score
        
        Why metadata:
        - Debug low-quality recommendations
        - A/B test different confidence thresholds
        - Explain why certain products recommended
        """
        if self.pool is None:
            await self.connect()
        
        if not retailrocket_item_ids:
            return []
        
        confidence_threshold = confidence_threshold or settings.confidence_threshold
        
        try:
            async with self.pool.acquire() as conn:
                query = """
                    SELECT product_id, latent_item_id, confidence_score, mapping_strategy
                    FROM latent_item_mappings
                    WHERE latent_item_id = ANY($1)
                      AND confidence_score >= $2
                    ORDER BY confidence_score DESC
                """
                rows = await conn.fetch(query, retailrocket_item_ids, confidence_threshold)
                
                # Convert to list of dicts
                mappings = [
                    {
                        'product_id': str(row['product_id']),
                        'latent_item_id': row['latent_item_id'],
                        'confidence_score': float(row['confidence_score']),
                        'mapping_strategy': row.get('mapping_strategy', 'unknown')
                    }
                    for row in rows
                ]
                
                return mappings
        
        except Exception as e:
            logger.error(f"Latent mapping with metadata failed: {e}")
            return []
    
    async def get_valid_latent_ids(self, confidence_threshold: float = None) -> List[int]:
        """
        Get all latent item IDs that have catalog mappings.
        
        Args:
            confidence_threshold: Minimum confidence score (default from config)
        
        Returns:
            List of latent item IDs that can be safely recommended
        
        Why needed:
        - Popularity model has 235K items from retailrocket
        - Only ~2K items have catalog mappings
        - Need to filter recommendations to mapped items only
        """
        if self.pool is None:
            await self.connect()
        
        confidence_threshold = confidence_threshold or settings.confidence_threshold
        
        try:
            async with self.pool.acquire() as conn:
                query = """
                    SELECT latent_item_id
                    FROM latent_item_mappings
                    WHERE confidence_score >= $1
                """
                rows = await conn.fetch(query, confidence_threshold)
                valid_ids = [row['latent_item_id'] for row in rows]
                logger.info(f"Found {len(valid_ids)} valid latent IDs with confidence >= {confidence_threshold}")
                return valid_ids
        except Exception as e:
            logger.error(f"Failed to fetch valid latent IDs: {e}")
            return []
    
    async def close(self):
        """Close database connection pool."""
        if self.pool:
            await self.pool.close()
            logger.info("Database connection pool closed")


# Global instance
_mapper_instance: Optional[LatentMapper] = None


def get_latent_mapper() -> LatentMapper:
    """Get or create global latent mapper instance."""
    global _mapper_instance
    if _mapper_instance is None:
        _mapper_instance = LatentMapper()
    return _mapper_instance
