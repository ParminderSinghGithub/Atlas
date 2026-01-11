"""
Session-Aware Re-ranking Module

Purpose:
- Track user session intent (categories viewed, recent products)
- Apply bounded, explainable re-ranking to recommendations
- Boost candidates matching session signals without overriding ML scores

Key Principles:
- MUST NOT override LightGBM ordering significantly
- Degrade gracefully if Redis unavailable
- Log all re-ranking decisions for explainability
- Session signals decay over time (last N minutes)

Session Signals Tracked:
1. Categories viewed in session
2. Products viewed recently
3. Search queries (future)

Re-ranking Strategy:
- Apply small boost (+0.1 to +0.3) to matching candidates
- Never move item more than 3 positions
- Preserve relative ordering within category

Usage:
    from app.session.reranker import SessionReranker
    
    reranker = await SessionReranker.create(redis_url)
    reranked = await reranker.apply_session_boost(
        user_id, candidates, scores
    )
"""
from typing import List, Dict, Optional, Tuple, Set
from uuid import UUID
import json
import time
from dataclasses import dataclass

try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class SessionSignals:
    """User session intent signals."""
    categories_viewed: Set[str]  # Category slugs
    products_viewed: Set[UUID]  # Product UUIDs
    last_updated: float  # Unix timestamp
    
    def is_stale(self, max_age_seconds: int = 1800) -> bool:
        """Check if session signals are stale (> 30 min)."""
        return (time.time() - self.last_updated) > max_age_seconds


class SessionReranker:
    """Apply session-aware re-ranking to recommendations."""
    
    # Re-ranking parameters
    CATEGORY_BOOST = 0.2  # Boost for matching category
    PRODUCT_BOOST = 0.3  # Boost for related products
    MAX_POSITION_SHIFT = 3  # Max positions to move up/down
    SESSION_TTL = 1800  # 30 minutes
    
    def __init__(self, redis_client: Optional[redis.Redis] = None):
        """
        Initialize session reranker.
        
        Args:
            redis_client: Async Redis client (optional)
        """
        self.redis = redis_client
        self.enabled = redis_client is not None
        
        if not self.enabled:
            logger.warning("Session re-ranking disabled (Redis not available)")
    
    @classmethod
    async def create(cls, redis_url: Optional[str] = None) -> "SessionReranker":
        """
        Create session reranker with Redis connection.
        
        Args:
            redis_url: Redis connection URL (optional)
        
        Returns:
            SessionReranker instance
        """
        if not REDIS_AVAILABLE:
            logger.warning("Redis library not installed, session re-ranking disabled")
            return cls(redis_client=None)
        
        if not redis_url:
            logger.info("Redis URL not provided, session re-ranking disabled")
            return cls(redis_client=None)
        
        try:
            redis_client = await redis.from_url(
                redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=2
            )
            
            # Test connection
            await redis_client.ping()
            logger.info("✓ Connected to Redis for session tracking")
            
            return cls(redis_client=redis_client)
        
        except Exception as e:
            logger.warning(f"Failed to connect to Redis: {e}")
            return cls(redis_client=None)
    
    def _session_key(self, user_id: str) -> str:
        """Generate Redis key for user session."""
        return f"session:{user_id}"
    
    async def track_category_view(self, user_id: str, category_slug: str):
        """
        Track category view in user session.
        
        Args:
            user_id: User identifier
            category_slug: Category slug viewed
        """
        if not self.enabled:
            return
        
        try:
            key = self._session_key(user_id)
            
            # Get existing signals
            signals = await self._get_signals(user_id)
            if signals is None:
                signals = SessionSignals(
                    categories_viewed=set(),
                    products_viewed=set(),
                    last_updated=time.time()
                )
            
            # Update
            signals.categories_viewed.add(category_slug)
            signals.last_updated = time.time()
            
            # Save
            await self._save_signals(user_id, signals)
            
            logger.debug(f"Tracked category view: user={user_id}, category={category_slug}")
        
        except Exception as e:
            logger.warning(f"Failed to track category view: {e}")
    
    async def track_product_view(self, user_id: str, product_id: UUID):
        """
        Track product view in user session.
        
        Args:
            user_id: User identifier
            product_id: Product UUID viewed
        """
        if not self.enabled:
            return
        
        try:
            key = self._session_key(user_id)
            
            # Get existing signals
            signals = await self._get_signals(user_id)
            if signals is None:
                signals = SessionSignals(
                    categories_viewed=set(),
                    products_viewed=set(),
                    last_updated=time.time()
                )
            
            # Update
            signals.products_viewed.add(product_id)
            signals.last_updated = time.time()
            
            # Save
            await self._save_signals(user_id, signals)
            
            logger.debug(f"Tracked product view: user={user_id}, product={product_id}")
        
        except Exception as e:
            logger.warning(f"Failed to track product view: {e}")
    
    async def _get_signals(self, user_id: str) -> Optional[SessionSignals]:
        """Load session signals from Redis."""
        if not self.enabled:
            return None
        
        try:
            key = self._session_key(user_id)
            data = await self.redis.get(key)
            
            if not data:
                return None
            
            parsed = json.loads(data)
            signals = SessionSignals(
                categories_viewed=set(parsed.get('categories_viewed', [])),
                products_viewed=set(UUID(pid) for pid in parsed.get('products_viewed', [])),
                last_updated=parsed.get('last_updated', time.time())
            )
            
            # Check staleness
            if signals.is_stale(self.SESSION_TTL):
                await self.redis.delete(key)
                return None
            
            return signals
        
        except Exception as e:
            logger.warning(f"Failed to load session signals: {e}")
            return None
    
    async def _save_signals(self, user_id: str, signals: SessionSignals):
        """Save session signals to Redis."""
        if not self.enabled:
            return
        
        try:
            key = self._session_key(user_id)
            data = {
                'categories_viewed': list(signals.categories_viewed),
                'products_viewed': [str(pid) for pid in signals.products_viewed],
                'last_updated': signals.last_updated
            }
            
            await self.redis.setex(
                key,
                self.SESSION_TTL,
                json.dumps(data)
            )
        
        except Exception as e:
            logger.warning(f"Failed to save session signals: {e}")
    
    async def apply_session_boost(
        self,
        user_id: str,
        candidates: List[UUID],
        scores: List[float],
        product_metadata: Dict[UUID, Dict]
    ) -> Tuple[List[UUID], List[float], Dict]:
        """
        Apply session-aware re-ranking to recommendations.
        
        Args:
            user_id: User identifier
            candidates: List of candidate product UUIDs
            scores: LightGBM scores for candidates
            product_metadata: Product metadata (includes category info)
        
        Returns:
            (reranked_candidates, reranked_scores, metadata)
        """
        if not self.enabled:
            return candidates, scores, {'session_reranking_applied': False}
        
        # Get session signals
        signals = await self._get_signals(user_id)
        
        if signals is None or (not signals.categories_viewed and not signals.products_viewed):
            logger.debug(f"No session signals for user {user_id}")
            return candidates, scores, {
                'session_reranking_applied': False,
                'reason': 'no_signals'
            }
        
        logger.info(f"Applying session re-ranking: user={user_id}")
        logger.info(f"  Categories viewed: {signals.categories_viewed}")
        logger.info(f"  Products viewed: {len(signals.products_viewed)}")
        
        # Calculate boosts
        boosted_scores = []
        boost_metadata = []
        
        for candidate, score in zip(candidates, scores):
            boost = 0.0
            reasons = []
            
            # Get product metadata
            metadata = product_metadata.get(candidate, {})
            category_id = metadata.get('category_id')
            category_name = metadata.get('category_name', '')
            
            # Category boost - match by ID or name/slug
            # Session tracks category_slug, but we match by name or ID
            category_match = False
            if category_id:
                # Check if category ID string is in viewed categories
                if str(category_id) in signals.categories_viewed:
                    category_match = True
            if category_name:
                # Check if category name matches (case-insensitive)
                for viewed_cat in signals.categories_viewed:
                    if viewed_cat.lower() in category_name.lower() or category_name.lower() in viewed_cat.lower():
                        category_match = True
                        break
            
            if category_match:
                boost += self.CATEGORY_BOOST
                reasons.append('category_match')
            
            # Product relation boost (viewed similar products)
            # Simple heuristic: if any product in session matches category
            if signals.products_viewed:
                # Direct product match
                if candidate in signals.products_viewed:
                    boost += self.PRODUCT_BOOST * 2  # Strong boost for viewed product
                    reasons.append('product_viewed')
                # Check if category matches any viewed product
                else:
                    for viewed_pid in signals.products_viewed:
                        viewed_meta = product_metadata.get(viewed_pid, {})
                        if viewed_meta.get('category_id') == category_id or viewed_meta.get('category_name') == category_name:
                            boost += self.PRODUCT_BOOST
                            reasons.append('related_product')
                            break
            
            boosted_score = score + boost
            boosted_scores.append(boosted_score)
            boost_metadata.append({
                'original_score': score,
                'boost': boost,
                'reasons': reasons
            })
        
        # Re-rank with position constraints
        # Create list of (index, score, uuid)
        ranked = list(zip(range(len(candidates)), boosted_scores, candidates, boost_metadata))
        ranked.sort(key=lambda x: x[1], reverse=True)
        
        # Apply position constraints (no more than MAX_POSITION_SHIFT)
        constrained = []
        for new_pos, (orig_pos, score, uuid, meta) in enumerate(ranked):
            position_shift = abs(new_pos - orig_pos)
            
            if position_shift > self.MAX_POSITION_SHIFT:
                # Limit shift
                clamped_pos = orig_pos + (self.MAX_POSITION_SHIFT if new_pos > orig_pos else -self.MAX_POSITION_SHIFT)
                constrained.append((clamped_pos, score, uuid, meta))
            else:
                constrained.append((new_pos, score, uuid, meta))
        
        # Final sort by constrained position
        constrained.sort(key=lambda x: x[0])
        
        # Extract reranked results
        reranked_candidates = [c[2] for c in constrained]
        reranked_scores = [c[1] for c in constrained]
        
        # Metadata
        boost_stats = {
            'session_reranking_applied': True,
            'categories_matched': list(signals.categories_viewed),
            'products_referenced': len(signals.products_viewed),
            'items_boosted': sum(1 for m in boost_metadata if m['boost'] > 0),
            'max_boost_applied': max((m['boost'] for m in boost_metadata), default=0)
        }
        
        logger.info(f"  ✓ Re-ranking complete: {boost_stats['items_boosted']} items boosted")
        
        return reranked_candidates, reranked_scores, boost_stats
    
    async def close(self):
        """Close Redis connection."""
        if self.redis:
            await self.redis.close()


# Global instance
_reranker_instance: Optional[SessionReranker] = None


async def get_session_reranker(redis_url: Optional[str] = None) -> SessionReranker:
    """Get or create global session reranker instance."""
    global _reranker_instance
    
    if _reranker_instance is None:
        _reranker_instance = await SessionReranker.create(redis_url)
    
    return _reranker_instance
