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
from __future__ import annotations
from typing import List, Dict, Optional, Tuple, Set, Union, Any
from uuid import UUID
import json
import time
from dataclasses import dataclass

try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    redis = None  # type: ignore
    REDIS_AVAILABLE = False

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class SessionSignals:
    """User session intent signals."""
    categories_viewed: Set[str]  # Category slugs / names
    products_viewed: Set[UUID]  # Product UUIDs
    product_categories: Dict[str, str]  # Map str(product_id) -> category_slug / name
    last_updated: float  # Unix timestamp
    
    def is_stale(self, max_age_seconds: int = 1800) -> bool:
        """Check if session signals are stale (> 30 min)."""
        return (time.time() - self.last_updated) > max_age_seconds


class SessionReranker:
    """Apply session-aware re-ranking to recommendations."""
    
    # Re-ranking parameters (relative score-space weights)
    CATEGORY_BOOST = 0.35  # Relative weight for matching category intent
    PRODUCT_BOOST = 0.30  # Relative weight for related products
    MAX_POSITION_SHIFT = 4  # Max positions to move up/down (bounded reranking)
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
                socket_connect_timeout=2
            )
            
            # Test connection
            await redis_client.ping()
            logger.info("[OK] Connected to Redis for session tracking")
            
            return cls(redis_client=redis_client)
        
        except Exception:
            logger.exception("Failed to connect to Redis for session tracking")
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
                    product_categories={},
                    last_updated=time.time()
                )
            
            # Update
            if category_slug:
                signals.categories_viewed.add(str(category_slug).strip().lower())
            signals.last_updated = time.time()
            
            # Save
            await self._save_signals(user_id, signals)
            
            logger.debug(f"Tracked category view: user={user_id}, category={category_slug}")
        
        except Exception:
            logger.exception(
                "Failed to track category view | user_id=%s | category_slug=%s",
                user_id,
                category_slug,
            )
    
    async def track_product_view(
        self,
        user_id: str,
        product_id: Union[UUID, str],
        category_slug: Optional[str] = None
    ):
        """
        Track product view in user session.
        
        Args:
            user_id: User identifier
            product_id: Product UUID viewed
            category_slug: Optional category slug for the viewed product
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
                    product_categories={},
                    last_updated=time.time()
                )
            
            # Update
            prod_uuid = UUID(str(product_id)) if not isinstance(product_id, UUID) else product_id
            signals.products_viewed.add(prod_uuid)
            
            if category_slug:
                clean_cat = str(category_slug).strip().lower()
                signals.categories_viewed.add(clean_cat)
                signals.product_categories[str(prod_uuid)] = clean_cat
            
            signals.last_updated = time.time()
            
            # Save
            await self._save_signals(user_id, signals)
            
            logger.debug(f"Tracked product view: user={user_id}, product={product_id}, category={category_slug}")
        
        except Exception:
            logger.exception(
                "Failed to track product view | user_id=%s | product_id=%s",
                user_id,
                product_id,
            )
    
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
            categories = {str(c).strip().lower() for c in parsed.get('categories_viewed', []) if c}
            products = set()
            for pid in parsed.get('products_viewed', []):
                try:
                    products.add(UUID(str(pid)))
                except Exception:
                    pass
            prod_cats = parsed.get('product_categories', {})
            
            signals = SessionSignals(
                categories_viewed=categories,
                products_viewed=products,
                product_categories=prod_cats,
                last_updated=parsed.get('last_updated', time.time())
            )
            
            # Check staleness
            if signals.is_stale(self.SESSION_TTL):
                await self.redis.delete(key)
                return None
            
            return signals
        
        except Exception:
            logger.exception("Failed to load session signals | user_id=%s", user_id)
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
                'product_categories': signals.product_categories,
                'last_updated': signals.last_updated
            }
            
            await self.redis.setex(
                key,
                self.SESSION_TTL,
                json.dumps(data)
            )
        except Exception:
            logger.exception("Failed to save session signals | user_id=%s", user_id)
    
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
        
        active_categories = set(signals.categories_viewed)
        for cat in signals.product_categories.values():
            if cat:
                active_categories.add(str(cat).strip().lower())
        
        viewed_product_uuids = set(signals.products_viewed)
        viewed_product_strs = {str(p) for p in signals.products_viewed}
        
        # Dynamic score-space scaling: calibrate boost relative to score distribution
        if scores and len(scores) > 0:
            score_span = max(float(max(scores)) - float(min(scores)), 1.0)
        else:
            score_span = 1.0

        effective_direct_product_boost = (self.PRODUCT_BOOST * 2.0) * score_span
        effective_category_boost = self.CATEGORY_BOOST * score_span
        effective_related_boost = self.PRODUCT_BOOST * score_span

        # Calculate boosts
        boosted_scores = []
        boost_metadata = []
        candidate_boost_map: Dict[Any, Dict] = {}
        matched_categories_set = set()
        
        for candidate, score in zip(candidates, scores):
            boost = 0.0
            reasons = []
            cand_uuid_str = str(candidate)
            
            # Get product metadata
            metadata = product_metadata.get(candidate) or product_metadata.get(UUID(cand_uuid_str)) or {}
            category_id = str(metadata.get('category_id', '')).strip().lower()
            category_name = str(metadata.get('category_name', '')).strip().lower()
            category_slug = str(metadata.get('category_slug', '')).strip().lower()
            
            # 1. Direct Product Match (viewed this exact product in current session)
            if candidate in viewed_product_uuids or cand_uuid_str in viewed_product_strs:
                boost += effective_direct_product_boost
                reasons.append('product_viewed')
                if category_slug:
                    matched_categories_set.add(category_slug)
                elif category_name:
                    matched_categories_set.add(category_name)
            
            # 2. Category Match / Related Product (Category viewed directly or via product view)
            category_matched = False
            for active_cat in active_categories:
                if not active_cat:
                    continue
                norm_active = active_cat.replace('-', ' ').replace('_', ' ')
                norm_name = category_name.replace('-', ' ').replace('_', ' ')
                norm_slug = category_slug.replace('-', ' ').replace('_', ' ')
                
                if (active_cat == category_slug or 
                    active_cat == category_id or 
                    active_cat in category_slug or 
                    category_slug in active_cat or 
                    norm_active in norm_name or 
                    norm_name in norm_active or 
                    norm_active in norm_slug or 
                    norm_slug in norm_active):
                    category_matched = True
                    matched_categories_set.add(category_slug or category_name or active_cat)
                    break
            
            if category_matched and 'product_viewed' not in reasons:
                boost += effective_category_boost
                reasons.append('category_match')
            
            # 3. Related Product Match via product_metadata (if viewed product was in metadata)
            if not category_matched and signals.products_viewed and 'product_viewed' not in reasons:
                for viewed_pid in viewed_product_uuids:
                    viewed_meta = product_metadata.get(viewed_pid) or product_metadata.get(str(viewed_pid)) or {}
                    if viewed_meta:
                        v_cat_id = str(viewed_meta.get('category_id', '')).strip().lower()
                        v_cat_name = str(viewed_meta.get('category_name', '')).strip().lower()
                        v_cat_slug = str(viewed_meta.get('category_slug', '')).strip().lower()
                        if ((category_id and v_cat_id == category_id) or
                            (category_slug and v_cat_slug == category_slug) or
                            (category_name and v_cat_name == category_name)):
                            boost += effective_related_boost
                            reasons.append('related_product')
                            matched_categories_set.add(category_slug or category_name)
                            break
            
            boosted_score = score + boost
            boosted_scores.append(boosted_score)
            meta_entry = {
                'candidate': candidate,
                'original_score': score,
                'boosted_score': boosted_score,
                'boost': boost,
                'reasons': reasons,
                'is_boosted': boost > 0
            }
            boost_metadata.append(meta_entry)
            candidate_boost_map[candidate] = meta_entry
            candidate_boost_map[cand_uuid_str] = meta_entry
        
        # Re-rank with position constraints
        ranked = list(zip(range(len(candidates)), boosted_scores, candidates, boost_metadata))
        ranked.sort(key=lambda x: x[1], reverse=True)
        
        # Apply position constraints (no more than MAX_POSITION_SHIFT)
        constrained = []
        for new_pos, (orig_pos, score, uuid, meta) in enumerate(ranked):
            position_shift = abs(new_pos - orig_pos)
            
            if position_shift > self.MAX_POSITION_SHIFT:
                clamped_pos = orig_pos + (self.MAX_POSITION_SHIFT if new_pos > orig_pos else -self.MAX_POSITION_SHIFT)
                constrained.append((clamped_pos, score, uuid, meta))
            else:
                constrained.append((new_pos, score, uuid, meta))
        
        # Final sort by constrained position
        constrained.sort(key=lambda x: x[0])
        
        # Extract reranked results
        reranked_candidates = [c[2] for c in constrained]
        reranked_scores = [c[1] for c in constrained]
        
        # Build candidate boost map
        boost_map = {str(c[2]): c[3] for c in constrained}
        for c in constrained:
            boost_map[c[2]] = c[3]
        
        # Metadata
        boost_stats = {
            'session_reranking_applied': True,
            'categories_matched': list(matched_categories_set) if matched_categories_set else list(signals.categories_viewed),
            'products_referenced': len(signals.products_viewed),
            'items_boosted': sum(1 for m in boost_metadata if m['boost'] > 0),
            'max_boost_applied': max((m['boost'] for m in boost_metadata), default=0.0),
            'boost_map': boost_map
        }
        
        logger.info(f"  [OK] Re-ranking complete: {boost_stats['items_boosted']} items boosted")
        
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
    
    if _reranker_instance is None or (not _reranker_instance.enabled and redis_url):
        _reranker_instance = await SessionReranker.create(redis_url)
    
    return _reranker_instance
