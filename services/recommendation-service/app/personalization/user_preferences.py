"""
User Preference Loader — Long-Term Personalization.

Architecture:
    PostgreSQL events table (permanent behavioral history)
        → single aggregate SQL query per user (indexed on user_id, ts)
        → compact UserPreferences object (top-N category slugs)
        → Redis cache (key=ltpref:{user_id}, TTL=1h)
        → returned to recommendation pipeline for pre-session boosting

Design decisions:
1. REUSES the existing asyncpg connection pool pattern (same as LatentMapper).
2. REUSES the existing Redis client pattern (same as SessionReranker).
3. One SQL query per cache miss — no N+1 queries.
4. Returns category slugs only; product-level boosts omitted (category
   signal is sufficient and avoids overfitting to specific products).
5. Guest/non-UUID users skip the DB lookup entirely (zero overhead).
6. Graceful degradation at every layer: Redis miss → DB query → fallback
   to empty preferences → normal recommendation behavior unchanged.

Score/boost design:
    The pipeline has two score spaces:
      a) category_similarity path: synthetic [1.0, 0.95, 0.90, ...]
      b) main path (popularity/LightGBM): model-scale floats

    The session reranker applies +0.2 per category match, +0.3 related,
    +0.6 direct product view — and re-sorts. This mechanism works purely
    on RELATIVE ordering, not on absolute score magnitude.

    Long-term boost uses the same relative approach with a SMALLER magnitude:
      +0.10 per matched preferred category (vs session's +0.20)
    This ensures session intent always dominates historical preference.
    MAX_LT_BOOST = +0.10 (single category, no stacking).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
from uuid import UUID

try:
    import asyncpg
    _ASYNCPG_AVAILABLE = True
except ImportError:
    asyncpg = None  # type: ignore
    _ASYNCPG_AVAILABLE = False

try:
    import redis.asyncio as _aioredis
    _REDIS_AVAILABLE = True
except ImportError:
    _aioredis = None  # type: ignore
    _REDIS_AVAILABLE = False

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_EVENT_WEIGHTS: Dict[str, int] = {
    "purchase": 3,
    "add_to_cart": 2,
    "view": 1,
    "click": 1,
}
_HISTORY_DAYS = 90           # Rolling window for behavioral history
_MAX_PREFERRED_CATEGORIES = 5  # Top-N categories to retain in profile
_LT_BOOST = 0.10             # Smaller than session CATEGORY_BOOST (0.20)
_MAX_LT_BOOST = 0.10         # Cap: only +0.10 even for multiple category matches
_CACHE_TTL = 3600            # 1-hour Redis TTL for preference profile
_CACHE_PREFIX = "ltpref:"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class UserPreferences:
    """Compact long-term preference profile for a single user."""
    user_id: str
    preferred_categories: List[str]  # Ordered by weight (strongest first)
    source: str = "none"             # "redis" | "postgres" | "none"
    fetched_at: float = field(default_factory=time.time)

    def is_empty(self) -> bool:
        return not self.preferred_categories

    def matches_category(self, category_slug: str, category_name: str = "") -> bool:
        """Return True if any preferred category overlaps with this item's category."""
        if not category_slug and not category_name:
            return False
        slug_norm = str(category_slug).strip().lower().replace("-", " ").replace("_", " ")
        name_norm = str(category_name).strip().lower().replace("-", " ").replace("_", " ")
        for pref in self.preferred_categories:
            pref_norm = pref.strip().lower().replace("-", " ").replace("_", " ")
            if not pref_norm:
                continue
            if (pref_norm == slug_norm or
                    pref_norm in slug_norm or
                    slug_norm in pref_norm or
                    pref_norm == name_norm or
                    pref_norm in name_norm or
                    name_norm in pref_norm):
                return True
        return False


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------
class UserPreferenceLoader:
    """
    Load persistent user preference profiles.

    Uses the same asyncpg pool pattern as LatentMapper and the same Redis
    pattern as SessionReranker — no new abstractions introduced.
    """

    def __init__(self) -> None:
        self.pool: Optional[asyncpg.Pool] = None
        self._redis_client: Optional[object] = None  # aioredis.Redis when available

    # ------------------------------------------------------------------
    # Startup helpers (called from main.py lifespan)
    # ------------------------------------------------------------------
    async def connect_db(self) -> None:
        """Create asyncpg connection pool (lazy, idempotent)."""
        if self.pool is not None:
            return
        try:
            db_url = settings.database_url.replace(
                "postgresql+asyncpg://", "postgresql://"
            )
            self.pool = await asyncpg.create_pool(
                db_url, min_size=1, max_size=5, command_timeout=5
            )
            await self._ensure_events_index()
            logger.info("UserPreferenceLoader: DB pool ready")
        except Exception:
            logger.exception("UserPreferenceLoader: failed to connect to DB — LT personalization disabled")
            self.pool = None

    async def connect_redis(self, redis_url: Optional[str]) -> None:
        """Create Redis client (lazy, idempotent, no-op if unavailable)."""
        if not _REDIS_AVAILABLE or not redis_url:
            return
        if self._redis_client is not None:
            return
        try:
            client = await _aioredis.from_url(
                redis_url, encoding="utf-8", socket_connect_timeout=2
            )
            await client.ping()
            self._redis_client = client
            logger.info("UserPreferenceLoader: Redis cache ready")
        except Exception:
            logger.warning("UserPreferenceLoader: Redis unavailable — will query DB directly")
            self._redis_client = None

    async def _ensure_events_index(self) -> None:
        """
        Create index on events(user_id, ts) if it does not exist.

        Called once at startup (after pool creation) — not per-request.
        Follows the same CREATE IF NOT EXISTS pattern used by events.py.
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_events_user_id_ts
                    ON events (user_id, ts DESC)
                    """
                )
            logger.info("UserPreferenceLoader: idx_events_user_id_ts ensured")
        except Exception:
            logger.warning(
                "UserPreferenceLoader: could not create events index "
                "(table may not exist yet — events written lazily)"
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def get_preferences(self, user_id: str) -> UserPreferences:
        """
        Return the long-term preference profile for a user.

        Lookup order:
          1. Redis cache (fast, O(1))
          2. PostgreSQL aggregate query (single query, index-backed)
          3. Empty profile (graceful fallback)

        Args:
            user_id: Authenticated user UUID string.

        Returns:
            UserPreferences with preferred_categories (possibly empty).
        """
        # Never look up guest/non-UUID IDs
        if not _is_valid_uuid(user_id):
            return UserPreferences(user_id=user_id, preferred_categories=[], source="none")

        # 1. Try Redis cache
        cached = await self._load_from_redis(user_id)
        if cached is not None:
            return cached

        # 2. Query PostgreSQL
        prefs = await self._load_from_db(user_id)

        # 3. Cache the result (even empty profiles to avoid hammering DB)
        await self._save_to_redis(user_id, prefs)
        return prefs

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    async def _load_from_redis(self, user_id: str) -> Optional[UserPreferences]:
        if self._redis_client is None:
            return None
        try:
            key = f"{_CACHE_PREFIX}{user_id}"
            raw = await self._redis_client.get(key)
            if raw is None:
                return None
            data = json.loads(raw)
            return UserPreferences(
                user_id=user_id,
                preferred_categories=data.get("preferred_categories", []),
                source="redis",
                fetched_at=data.get("fetched_at", time.time()),
            )
        except Exception:
            logger.warning("UserPreferenceLoader: Redis read failed for %s", user_id)
            return None

    async def _save_to_redis(self, user_id: str, prefs: UserPreferences) -> None:
        if self._redis_client is None:
            return
        try:
            key = f"{_CACHE_PREFIX}{user_id}"
            data = json.dumps(
                {
                    "preferred_categories": prefs.preferred_categories,
                    "fetched_at": prefs.fetched_at,
                }
            )
            await self._redis_client.setex(key, _CACHE_TTL, data)
        except Exception:
            logger.warning("UserPreferenceLoader: Redis write failed for %s", user_id)

    async def _load_from_db(self, user_id: str) -> UserPreferences:
        """
        Single SQL aggregate query to compute category preferences.

        Query joins events → latent_item_mappings → products → categories
        to resolve product_id strings to real category slugs.  This avoids
        N+1 fetches and returns weighted category counts in one round-trip.

        Weight: purchase=3, add_to_cart=2, view=1, click=1.
        """
        if self.pool is None:
            try:
                await self.connect_db()
            except Exception:
                pass
        if self.pool is None:
            return UserPreferences(user_id=user_id, preferred_categories=[], source="none")

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT
                        cat.slug AS category_slug,
                        SUM(
                            CASE e.event_type
                                WHEN 'purchase'    THEN 3
                                WHEN 'add_to_cart' THEN 2
                                ELSE 1
                            END
                        ) AS weighted_score
                    FROM events e
                    JOIN products p
                        ON p.id = e.product_id::uuid
                    JOIN categories cat
                        ON cat.id = p.category_id
                    WHERE e.user_id = $1
                      AND e.event_type IN ('view', 'click', 'add_to_cart', 'purchase')
                      AND e.product_id IS NOT NULL
                      AND e.ts >= NOW() - INTERVAL '90 days'
                    GROUP BY cat.slug
                    ORDER BY weighted_score DESC
                    LIMIT $2
                    """,
                    user_id,
                    _MAX_PREFERRED_CATEGORIES,
                )

            preferred = [row["category_slug"] for row in rows if row["category_slug"]]
            logger.info(
                "UserPreferenceLoader: DB query | user=%s | preferred=%s",
                user_id,
                preferred,
            )
            return UserPreferences(
                user_id=user_id,
                preferred_categories=preferred,
                source="postgres" if preferred else "none",
            )
        except Exception:
            logger.exception(
                "UserPreferenceLoader: DB query failed for user %s — falling back to empty profile",
                user_id,
            )
            return UserPreferences(user_id=user_id, preferred_categories=[], source="none")

    async def close(self) -> None:
        """Release resources on shutdown."""
        if self.pool:
            await self.pool.close()
        if self._redis_client:
            await self._redis_client.close()


# ---------------------------------------------------------------------------
# Boost application (pure function — no I/O)
# ---------------------------------------------------------------------------
def apply_long_term_boost(
    candidates: List[UUID],
    scores: List[float],
    product_metadata: Dict,
    preferences: UserPreferences,
) -> tuple[List[UUID], List[float], Dict]:
    """
    Apply long-term category preference boosts to candidates.

    Returns (candidates, boosted_scores, lt_meta).

    Design:
    - Boost = +0.10 for each candidate whose category matches a preferred one.
    - Max boost per item = LT_BOOST (_MAX_LT_BOOST), regardless of how many
      preferred categories match (avoids over-amplification).
    - Max position shift = 2 (more conservative than session's 3).
    - Re-sorts candidates by boosted score.

    This function is intentionally score-space-agnostic: it works on
    relative ordering, not absolute magnitudes, exactly like the session
    reranker — so it is safe for all strategies (popularity, LightGBM,
    category_similarity).
    """
    if preferences.is_empty():
        return candidates, scores, {"applied": False, "preferences_source": "none"}

    # Dynamic score-space scaling: calibrated relative to score distribution
    if scores and len(scores) > 0:
        score_span = max(float(max(scores)) - float(min(scores)), 1.0)
    else:
        score_span = 1.0

    effective_lt_boost = _MAX_LT_BOOST * score_span
    max_lt_position_shift = 2

    boosted_scores: List[float] = []
    boost_flags: List[bool] = []
    boost_reasons: List[str] = []

    for candidate, score in zip(candidates, scores):
        meta = product_metadata.get(candidate) or product_metadata.get(str(candidate)) or {}
        cat_slug = str(meta.get("category_slug", "")).strip().lower()
        cat_name = str(meta.get("category_name", "")).strip().lower()

        if preferences.matches_category(cat_slug, cat_name):
            boost = effective_lt_boost
            boosted_scores.append(score + boost)
            boost_flags.append(True)
            boost_reasons.append(cat_slug or cat_name)
        else:
            boosted_scores.append(score)
            boost_flags.append(False)
            boost_reasons.append("")

    # Re-rank by boosted score (descending) with bounded position shift
    ranked = list(zip(range(len(candidates)), boosted_scores, candidates, boost_flags, boost_reasons))
    ranked.sort(key=lambda x: x[1], reverse=True)

    constrained = []
    for new_pos, (orig_pos, score, cand, flag, reason) in enumerate(ranked):
        position_shift = abs(new_pos - orig_pos)
        if position_shift > max_lt_position_shift:
            clamped_pos = orig_pos + (max_lt_position_shift if new_pos > orig_pos else -max_lt_position_shift)
            constrained.append((clamped_pos, score, cand, flag, reason))
        else:
            constrained.append((new_pos, score, cand, flag, reason))

    constrained.sort(key=lambda x: x[0])

    reranked_candidates = [c[2] for c in constrained]
    reranked_scores = [c[1] for c in constrained]
    boosted_flags_final = [c[3] for c in constrained]
    reasons_final = [c[4] for c in constrained]

    items_boosted = sum(1 for f in boosted_flags_final if f)
    matched_categories = list(dict.fromkeys(r for r in reasons_final if r))  # dedup + preserve order
    max_boost = effective_lt_boost if items_boosted > 0 else 0.0

    # Build boost_map for use by routes.py
    boost_map = {}
    for cand, is_b, reason in zip(reranked_candidates, boosted_flags_final, reasons_final):
        entry = {"is_boosted": is_b, "boost": effective_lt_boost if is_b else 0.0, "reason": reason}
        boost_map[cand] = entry
        boost_map[str(cand)] = entry

    lt_meta = {
        "applied": True,
        "preferences_source": preferences.source,
        "categories_considered": preferences.preferred_categories,
        "categories_matched": matched_categories,
        "items_boosted": items_boosted,
        "max_boost_applied": max_boost,
        "boost_map": boost_map,
    }
    return reranked_candidates, reranked_scores, lt_meta


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _is_valid_uuid(value: str) -> bool:
    """Return True only for authentic UUID-format user IDs (not guest strings)."""
    try:
        UUID(str(value))
        return True
    except (ValueError, AttributeError):
        return False


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_loader_instance: Optional[UserPreferenceLoader] = None


def get_user_preference_loader() -> UserPreferenceLoader:
    """Return the global UserPreferenceLoader singleton."""
    global _loader_instance
    if _loader_instance is None:
        _loader_instance = UserPreferenceLoader()
    return _loader_instance
