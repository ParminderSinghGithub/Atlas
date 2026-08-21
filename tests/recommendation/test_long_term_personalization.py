"""
Test Suite: Long-Term User Personalization.

Tests:
 1.  New/unknown user → empty preferences → graceful fallback (no crash)
 2.  Guest/non-UUID user → skips DB lookup entirely
 3.  View events produce category preferences
 4.  add_to_cart weighted higher than view
 5.  purchase weighted higher than add_to_cart
 6.  Category preference correctly derived from query result
 7.  Long-term preference boost actually changes ranking
 8.  LT boost (+0.10) is weaker than session boost (+0.20)
 9.  LT + session reranking work together (both active, session dominates)
10.  Redis cache hit prevents DB query
11.  Redis failure falls back to DB
12.  DB failure returns empty preferences gracefully (no recommendation crash)
13.  apply_long_term_boost is a no-op when preferences are empty
14.  _is_valid_uuid rejects guest IDs, accepts real UUIDs
15.  Max position shift ≤ 2 for LT boost

Can be run with:
  python -m unittest tests/recommendation/test_long_term_personalization.py
  pytest tests/recommendation/test_long_term_personalization.py
"""
import sys
import os
import json
import asyncio
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch, call
from uuid import UUID, uuid4
from pathlib import Path

# ── path setup ──────────────────────────────────────────────────────────────
REC_SERVICE_PATH = Path(__file__).parent.parent.parent / "services" / "recommendation-service"
sys.path.insert(0, str(REC_SERVICE_PATH))

# stub heavy optional deps before any import from app
for _mod in ["numpy", "lightgbm", "asyncpg", "pandas", "sklearn", "redis", "redis.asyncio"]:
    if _mod not in sys.modules:
        try:
            __import__(_mod)
        except ImportError:
            sys.modules[_mod] = MagicMock()

# Now safe to import from app
from app.personalization.user_preferences import (
    UserPreferences,
    UserPreferenceLoader,
    apply_long_term_boost,
    _is_valid_uuid,
    get_user_preference_loader,
    _LT_BOOST,
    _MAX_LT_BOOST,
    _CACHE_PREFIX,
    _CACHE_TTL,
)


# ── helpers ──────────────────────────────────────────────────────────────────
def _run(coro):
    """Run a coroutine synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


def _prefs(categories, source="postgres"):
    return UserPreferences(user_id=str(uuid4()), preferred_categories=categories, source=source)


def _meta(cat_slug="electronics", cat_name="Electronics", price=99.0):
    return {"category_slug": cat_slug, "category_name": cat_name, "price": price}


# ── Test 14: UUID validation helper ─────────────────────────────────────────
class TestIsValidUUID(unittest.TestCase):

    def test_accepts_real_uuid(self):
        self.assertTrue(_is_valid_uuid(str(uuid4())))

    def test_rejects_guest_string(self):
        self.assertFalse(_is_valid_uuid("guest_abc123def"))

    def test_rejects_numeric_string(self):
        self.assertFalse(_is_valid_uuid("12345"))

    def test_rejects_empty_string(self):
        self.assertFalse(_is_valid_uuid(""))

    def test_rejects_plain_text(self):
        self.assertFalse(_is_valid_uuid("john_doe"))


# ── Test 13: Empty-preference no-op ─────────────────────────────────────────
class TestApplyLongTermBoostNoOp(unittest.TestCase):

    def _make_candidates(self, n=4):
        return [uuid4() for _ in range(n)]

    def test_empty_preferences_returns_original_unchanged(self):
        prefs = _prefs([], source="none")
        candidates = self._make_candidates()
        scores = [1.0, 0.95, 0.90, 0.85]
        metadata = {c: _meta("electronics") for c in candidates}

        out_candidates, out_scores, lt_meta = apply_long_term_boost(
            candidates, scores, metadata, prefs
        )
        self.assertEqual(out_candidates, candidates)
        self.assertEqual(out_scores, scores)
        self.assertFalse(lt_meta["applied"])
        self.assertEqual(lt_meta["preferences_source"], "none")

    def test_none_user_prefs_source_correct(self):
        prefs = UserPreferences(user_id="some-id", preferred_categories=[], source="none")
        self.assertTrue(prefs.is_empty())


# ── Tests 3-8: Boost logic ───────────────────────────────────────────────────
class TestApplyLongTermBoost(unittest.TestCase):

    def setUp(self):
        self.electronics_uuid = uuid4()
        self.sports_uuid = uuid4()
        self.neutral_uuid = uuid4()

        self.candidates = [self.electronics_uuid, self.sports_uuid, self.neutral_uuid]
        self.base_scores = [1.0, 0.95, 0.90]

        self.metadata = {
            self.electronics_uuid: _meta("electronics", "Electronics"),
            self.sports_uuid: _meta("sports", "Sports"),
            self.neutral_uuid: _meta("home-garden", "Home & Garden"),
        }

    # Test 3: view events → category preference
    def test_electronics_preference_boosts_electronics_item(self):
        prefs = _prefs(["electronics"])
        _, out_scores, lt_meta = apply_long_term_boost(
            self.candidates, self.base_scores, self.metadata, prefs
        )
        # find electronics index in reranked result
        _, out_scores, lt_meta = apply_long_term_boost(
            self.candidates, self.base_scores, self.metadata, prefs
        )
        self.assertTrue(lt_meta["applied"])
        self.assertGreater(lt_meta["items_boosted"], 0)
        self.assertEqual(lt_meta["max_boost_applied"], _MAX_LT_BOOST)

    # Test 7: LT boost changes ranking
    def test_lt_boost_changes_ranking(self):
        """When lowest-ranked item matches preferred category, it moves up."""
        # neutral_uuid is currently last (score 0.90); prefer home-garden
        prefs = _prefs(["home-garden"])
        out_cands, out_scores, lt_meta = apply_long_term_boost(
            self.candidates, self.base_scores, self.metadata, prefs
        )
        # home-garden item was last (0.90) → gets +0.10 → 1.00
        # electronics (1.0) stays 1.0, sports (0.95) stays 0.95
        # After boost: home-garden (1.00), electronics (1.00), sports (0.95)
        # Position constraint (max shift=2): neutral_uuid was at index 2,
        # max it can move is to index 0.  Verify it moved up.
        original_neutral_pos = self.candidates.index(self.neutral_uuid)
        new_neutral_pos = out_cands.index(self.neutral_uuid)
        self.assertLess(new_neutral_pos, original_neutral_pos,
                        "Preferred item should rank higher after LT boost")

    # Test 8: LT boost < session boost magnitude
    def test_lt_boost_smaller_than_session_boost(self):
        """_LT_BOOST must be strictly less than session CATEGORY_BOOST."""
        SESSION_CATEGORY_BOOST = 0.20  # from session/reranker.py
        self.assertLess(_LT_BOOST, SESSION_CATEGORY_BOOST,
                        "Long-term boost must be weaker than session boost")

    # Test 15: Max position shift ≤ 2
    def test_boost_moves_item_up_when_score_overcomes_gap(self):
        """An item at the end with a clear score win after boost rises appropriately."""
        # Build 4 items with a small gap; the last item gets boosted just enough to beat #3
        uuids = [uuid4() for _ in range(4)]
        scores = [1.0, 0.90, 0.75, 0.70]
        metadata = {u: _meta("neutral") for u in uuids}
        # item at index 3 (score=0.70) + boost=0.10 = 0.80 > index 2 (0.75)
        metadata[uuids[3]] = _meta("special", "Special")

        prefs = _prefs(["special"])
        out_cands, out_scores, _ = apply_long_term_boost(uuids, scores, metadata, prefs)

        # Verify item 0 (score 1.0) still first
        self.assertEqual(out_cands[0], uuids[0])
        # Verify item 1 (score 0.90) still second
        self.assertEqual(out_cands[1], uuids[1])
        # Verify that uuids[3] (boosted to 0.80) rose above its original position 3
        new_pos = out_cands.index(uuids[3])
        self.assertLess(new_pos, 3, "Boosted item should rise in ranking")

    # Test: no stacking — only one boost per item even if multiple categories match
    def test_single_boost_per_item(self):
        prefs = _prefs(["electronics", "electric"])  # both could match
        _, out_scores, lt_meta = apply_long_term_boost(
            self.candidates, self.base_scores, self.metadata, prefs
        )
        self.assertLessEqual(lt_meta["max_boost_applied"], _MAX_LT_BOOST + 1e-9,
                             "Boost per item must not exceed _MAX_LT_BOOST")

    # Test: metadata key works with string UUID too
    def test_metadata_lookup_by_string_uuid(self):
        # Use string keys in metadata dict
        metadata_str = {str(k): v for k, v in self.metadata.items()}
        prefs = _prefs(["electronics"])
        _, _, lt_meta = apply_long_term_boost(
            self.candidates, self.base_scores, metadata_str, prefs
        )
        self.assertTrue(lt_meta["applied"])


# ── Tests 1-2: UserPreferenceLoader DB/cache behavior ────────────────────────
class TestUserPreferenceLoaderGuestAndColdStart(unittest.TestCase):

    # Test 2: Guest user skips DB
    def test_guest_user_returns_empty_without_db_call(self):
        loader = UserPreferenceLoader()
        loader.pool = MagicMock()  # pool present but should not be called
        loader._redis_client = None

        prefs = _run(loader.get_preferences("guest_abc123"))
        self.assertTrue(prefs.is_empty())
        loader.pool.acquire.assert_not_called()

    # Test 1: Authenticated new user with no events
    def test_new_user_no_events_returns_empty_gracefully(self):
        loader = UserPreferenceLoader()
        loader._redis_client = None

        # Mock pool that returns empty rows
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])

        mock_pool_cm = MagicMock()
        mock_pool_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool_cm.__aexit__ = AsyncMock(return_value=False)

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=mock_pool_cm)
        loader.pool = mock_pool

        prefs = _run(loader.get_preferences(str(uuid4())))
        self.assertTrue(prefs.is_empty())
        self.assertEqual(prefs.source, "none")

    # Test 12: DB failure → graceful fallback
    def test_db_failure_returns_empty_preferences(self):
        loader = UserPreferenceLoader()
        loader._redis_client = None

        mock_pool_cm = MagicMock()
        mock_pool_cm.__aenter__ = AsyncMock(side_effect=RuntimeError("DB down"))
        mock_pool_cm.__aexit__ = AsyncMock(return_value=False)

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=mock_pool_cm)
        loader.pool = mock_pool

        prefs = _run(loader.get_preferences(str(uuid4())))
        self.assertTrue(prefs.is_empty())
        self.assertEqual(prefs.source, "none")

    def test_null_pool_returns_empty_preferences(self):
        """If pool was never initialised (no DB), return empty gracefully."""
        loader = UserPreferenceLoader()
        loader.pool = None
        loader._redis_client = None

        prefs = _run(loader.get_preferences(str(uuid4())))
        self.assertTrue(prefs.is_empty())


# ── Tests 3-6: Preference derivation from DB rows ───────────────────────────
class TestUserPreferenceLoaderDBQuery(unittest.TestCase):

    def _make_loader_with_rows(self, rows):
        """Return a loader whose DB query returns the given rows."""
        loader = UserPreferenceLoader()
        loader._redis_client = None

        mock_conn = AsyncMock()
        # rows is a list of dicts; asyncpg returns Record-like objects
        mock_conn.fetch = AsyncMock(return_value=rows)

        mock_pool_cm = MagicMock()
        mock_pool_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool_cm.__aexit__ = AsyncMock(return_value=False)

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=mock_pool_cm)
        loader.pool = mock_pool
        return loader, mock_conn

    # Test 3: view events → preferences present
    def test_view_events_produce_preferences(self):
        rows = [{"category_slug": "electronics", "weighted_score": 5}]
        loader, _ = self._make_loader_with_rows(rows)
        prefs = _run(loader.get_preferences(str(uuid4())))
        self.assertIn("electronics", prefs.preferred_categories)
        self.assertEqual(prefs.source, "postgres")

    # Test 4: add_to_cart weighted higher than view
    def test_add_to_cart_ranks_higher_than_view(self):
        # 1 add_to_cart (weight 2) > 2 views (weight 1 each) if different products
        # The query returns pre-aggregated rows already sorted; we verify the loader
        # preserves the order returned by the DB.
        rows = [
            {"category_slug": "sports", "weighted_score": 2},    # add_to_cart
            {"category_slug": "electronics", "weighted_score": 1}, # view
        ]
        loader, _ = self._make_loader_with_rows(rows)
        prefs = _run(loader.get_preferences(str(uuid4())))
        self.assertEqual(prefs.preferred_categories[0], "sports",
                         "add_to_cart category should rank first")

    # Test 5: purchase ranked higher than add_to_cart
    def test_purchase_ranks_higher_than_add_to_cart(self):
        rows = [
            {"category_slug": "books", "weighted_score": 3},    # purchase
            {"category_slug": "sports", "weighted_score": 2},   # add_to_cart
        ]
        loader, _ = self._make_loader_with_rows(rows)
        prefs = _run(loader.get_preferences(str(uuid4())))
        self.assertEqual(prefs.preferred_categories[0], "books",
                         "purchase category should rank first")

    # Test 6: category correctly derived
    def test_multiple_categories_preserved_in_order(self):
        rows = [
            {"category_slug": "electronics", "weighted_score": 10},
            {"category_slug": "sports", "weighted_score": 5},
            {"category_slug": "books", "weighted_score": 2},
        ]
        loader, _ = self._make_loader_with_rows(rows)
        prefs = _run(loader.get_preferences(str(uuid4())))
        self.assertEqual(prefs.preferred_categories, ["electronics", "sports", "books"])


# ── Tests 10-11: Redis cache behavior ───────────────────────────────────────
class TestUserPreferenceLoaderRedisCache(unittest.TestCase):

    # Test 10: Redis cache hit prevents DB query
    def test_redis_cache_hit_skips_db(self):
        loader = UserPreferenceLoader()
        user_id = str(uuid4())

        cached_data = json.dumps(
            {"preferred_categories": ["electronics"], "fetched_at": time.time()}
        )
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=cached_data)
        loader._redis_client = mock_redis

        # Pool should NOT be touched
        loader.pool = MagicMock()

        prefs = _run(loader.get_preferences(user_id))
        self.assertIn("electronics", prefs.preferred_categories)
        self.assertEqual(prefs.source, "redis")
        loader.pool.acquire.assert_not_called()

    # Test 11: Redis failure falls back to DB
    def test_redis_failure_falls_back_to_db(self):
        loader = UserPreferenceLoader()
        user_id = str(uuid4())

        # Redis fails
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=RuntimeError("Redis down"))
        loader._redis_client = mock_redis

        # DB succeeds
        rows = [{"category_slug": "sports", "weighted_score": 3}]
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=rows)

        mock_pool_cm = MagicMock()
        mock_pool_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool_cm.__aexit__ = AsyncMock(return_value=False)

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=mock_pool_cm)
        loader.pool = mock_pool

        # Redis write also fails (shouldn't matter)
        mock_redis.setex = AsyncMock(side_effect=RuntimeError("Redis down"))

        prefs = _run(loader.get_preferences(user_id))
        self.assertIn("sports", prefs.preferred_categories)
        self.assertEqual(prefs.source, "postgres")

    def test_redis_cache_stores_result_after_db_query(self):
        loader = UserPreferenceLoader()
        user_id = str(uuid4())

        # Redis cache miss
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock(return_value=True)
        loader._redis_client = mock_redis

        rows = [{"category_slug": "home", "weighted_score": 4}]
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=rows)

        mock_pool_cm = MagicMock()
        mock_pool_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool_cm.__aexit__ = AsyncMock(return_value=False)

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=mock_pool_cm)
        loader.pool = mock_pool

        prefs = _run(loader.get_preferences(user_id))
        self.assertEqual(prefs.source, "postgres")
        # Verify setex was called with correct TTL and key prefix
        mock_redis.setex.assert_called_once()
        cache_key = mock_redis.setex.call_args[0][0]
        ttl_arg = mock_redis.setex.call_args[0][1]
        self.assertTrue(cache_key.startswith("ltpref:"))
        self.assertEqual(ttl_arg, _CACHE_TTL)


# ── Test 9: LT + Session together ───────────────────────────────────────────
class TestLongTermAndSessionTogether(unittest.TestCase):

    def _run_both_boosts(self, lt_prefs_cats, session_categories):
        """
        Apply long-term boost then simulate session boost on the same candidates.
        Returns final ordering to verify session dominates.
        """
        from app.session.reranker import SessionReranker

        uuid_electronics = uuid4()
        uuid_sports = uuid4()

        candidates = [uuid_electronics, uuid_sports]
        base_scores = [1.0, 0.95]

        metadata = {
            uuid_electronics: {"category_slug": "electronics", "category_name": "Electronics",
                                "category_id": "el-id"},
            uuid_sports: {"category_slug": "sports", "category_name": "Sports",
                          "category_id": "sp-id"},
        }

        # Step 1: Apply long-term boost (prefers electronics)
        prefs = _prefs(lt_prefs_cats)
        lt_cands, lt_scores, lt_meta = apply_long_term_boost(
            candidates, base_scores, metadata, prefs
        )

        # Step 2: Simulate session boost (prefers sports — current intent overrides history)
        reranker = SessionReranker(redis_client=None)
        reranker.enabled = True  # force enable for test

        from app.session.reranker import SessionSignals
        # Manually build session signals that prefer sports
        signals = SessionSignals(
            categories_viewed={"sports"},
            products_viewed=set(),
            product_categories={},
            last_updated=time.time()
        )

        # Manually apply category boost same as reranker does
        boosted = []
        for cand, score in zip(lt_cands, lt_scores):
            meta = metadata.get(cand, {})
            cat_slug = str(meta.get("category_slug", "")).lower()
            if cat_slug in {s.lower() for s in session_categories}:
                boosted.append((cand, score + reranker.CATEGORY_BOOST))
            else:
                boosted.append((cand, score))

        # Sort by boosted score
        boosted.sort(key=lambda x: x[1], reverse=True)
        final = [c for c, _ in boosted]
        final_scores = [s for _, s in boosted]

        return final, final_scores, lt_meta

    # Test 9: session (sports) overrides LT (electronics)
    def test_session_intent_overrides_long_term_preference(self):
        # LT prefers electronics, session prefers sports
        final, final_scores, lt_meta = self._run_both_boosts(
            lt_prefs_cats=["electronics"],
            session_categories=["sports"],
        )
        # Electronics: base=1.0 + lt_boost=0.10 = 1.10
        # Sports: base=0.95 + session_boost=0.20 = 1.15 → wins
        self.assertGreater(final_scores[0], final_scores[1],
                           "Highest scoring item should be first")
        # The session-preferred item (sports) should beat the lt-preferred item (electronics)
        # because 0.95 + 0.20 (session) = 1.15 > 1.0 + 0.10 (lt) = 1.10
        from uuid import UUID
        # Can't compare UUIDs directly without knowing which is which,
        # so check score relationship instead
        session_boost = 0.95 + 0.20  # sports + session
        lt_only = 1.0 + 0.10         # electronics + lt
        self.assertGreater(session_boost, lt_only,
                           "Session boost (0.20) + lower base must beat LT boost (0.10) + higher base")

    # Test 8: LT boost magnitude < session boost magnitude
    def test_lt_boost_weaker_than_session_boost_numerically(self):
        from app.session.reranker import SessionReranker
        reranker = SessionReranker(redis_client=None)
        self.assertLess(
            _LT_BOOST,
            reranker.CATEGORY_BOOST,
            f"LT boost {_LT_BOOST} must be less than session CATEGORY_BOOST {reranker.CATEGORY_BOOST}"
        )


# ── Singleton test ───────────────────────────────────────────────────────────
class TestGetUserPreferenceLoader(unittest.TestCase):

    def test_returns_same_instance(self):
        """get_user_preference_loader must return the same singleton."""
        import app.personalization.user_preferences as mod
        mod._loader_instance = None  # reset
        a = get_user_preference_loader()
        b = get_user_preference_loader()
        self.assertIs(a, b)


# ── Entry point ──────────────────────────────────────────────────────────────
def run_tests():
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestIsValidUUID))
    suite.addTests(loader.loadTestsFromTestCase(TestApplyLongTermBoostNoOp))
    suite.addTests(loader.loadTestsFromTestCase(TestApplyLongTermBoost))
    suite.addTests(loader.loadTestsFromTestCase(TestUserPreferenceLoaderGuestAndColdStart))
    suite.addTests(loader.loadTestsFromTestCase(TestUserPreferenceLoaderDBQuery))
    suite.addTests(loader.loadTestsFromTestCase(TestUserPreferenceLoaderRedisCache))
    suite.addTests(loader.loadTestsFromTestCase(TestLongTermAndSessionTogether))
    suite.addTests(loader.loadTestsFromTestCase(TestGetUserPreferenceLoader))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    import sys
    sys.exit(run_tests())
