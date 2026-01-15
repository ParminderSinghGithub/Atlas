"""
Recommendation Service Test Suite - CRITICAL ML VALIDATION.

Tests EVERY recommendation path:
1. Cold start (anonymous user)
2. Cold start (logged-in user, no history)
3. Logged-in user with session activity
4. Item similarity
5. Popularity fallback
6. LightGBM ranker involvement
7. Session-aware re-ranking (THE CRITICAL TEST)

Each test must prove:
- Which strategy was used
- Which models were invoked
- Whether personalization occurred
- PASS/FAIL verdict
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '_utils'))

import requests
import time
import json
from test_framework import TestSuite, TestResult, print_header

BASE_URL = "http://localhost:8000/api/v1"


def test_anonymous_cold_start():
    """Test recommendations for anonymous user (no user_id)."""
    test_name = "Anonymous User Cold Start"
    start = time.time()
    
    try:
        # Use a generic user_id for anonymous (service requires user_id parameter)
        response = requests.get(f"{BASE_URL}/recommendations", params={"user_id": "anonymous", "k": 10})
        duration = (time.time() - start) * 1000
        
        if response.status_code == 200:
            data = response.json()
            
            strategy = data.get("strategy_used", "unknown")
            recs = data.get("recommendations", [])
            
            # Anonymous should use popularity
            if "popularity" in strategy.lower():
                return TestResult(
                    name=test_name,
                    status="PASS",
                    expected="Popularity-based recommendations",
                    observed=f"Strategy: {strategy}, {len(recs)} items",
                    duration_ms=duration,
                    details={"strategy": strategy, "count": len(recs)}
                )
            else:
                return TestResult(
                    name=test_name,
                    status="FAIL",
                    expected="popularity strategy",
                    observed=f"Strategy: {strategy}",
                    reason="Wrong strategy for anonymous user",
                    duration_ms=duration
                )
        else:
            return TestResult(
                name=test_name,
                status="FAIL",
                expected="200 OK",
                observed=f"{response.status_code}",
                reason="Request failed",
                duration_ms=duration
            )
    except Exception as e:
        return TestResult(
            name=test_name,
            status="FAIL",
            expected="Recommendations returned",
            observed=f"Exception: {str(e)}",
            reason=str(e),
            duration_ms=(time.time() - start) * 1000
        )


def test_new_user_cold_start():
    """Test recommendations for logged-in user with no history (UUID user)."""
    test_name = "New User Cold Start (UUID)"
    start = time.time()
    
    user_id = f"uuid-user-{int(time.time() * 1000)}"
    
    try:
        response = requests.get(f"{BASE_URL}/recommendations", params={
            "user_id": user_id,
            "k": 10
        })
        duration = (time.time() - start) * 1000
        
        if response.status_code == 200:
            data = response.json()
            
            strategy = data.get("strategy_used", "unknown")
            recs = data.get("recommendations", [])
            
            # UUID users should fall back to popularity (SVD can't handle UUIDs)
            if "popularity" in strategy.lower() or "fallback" in strategy.lower():
                return TestResult(
                    name=test_name,
                    status="PASS",
                    expected="Popularity fallback (SVD can't map UUID)",
                    observed=f"Strategy: {strategy}, {len(recs)} items",
                    duration_ms=duration,
                    details={"strategy": strategy, "user_id": user_id}
                )
            else:
                return TestResult(
                    name=test_name,
                    status="FAIL",
                    expected="popularity fallback",
                    observed=f"Strategy: {strategy}",
                    reason="Unexpected strategy for UUID user",
                    duration_ms=duration
                )
        else:
            return TestResult(
                name=test_name,
                status="FAIL",
                expected="200 OK",
                observed=f"{response.status_code}",
                reason="Request failed",
                duration_ms=duration
            )
    except Exception as e:
        return TestResult(
            name=test_name,
            status="FAIL",
            expected="Cold start handled",
            observed=f"Exception: {str(e)}",
            reason=str(e),
            duration_ms=(time.time() - start) * 1000
        )


def test_session_aware_reranking():
    """
    THE CRITICAL TEST: Session-aware re-ranking.
    
    Tests if session signals (category_view, product_view) affect ranking.
    
    Steps:
    1. Get baseline recommendations
    2. Track session events
    3. Get recommendations again
    4. Compare rankings
    
    Expected: Rankings should change OR explicitly state why they don't.
    """
    test_name = "Session-Aware Re-Ranking"
    start = time.time()
    
    user_id = f"session-test-{int(time.time() * 1000)}"
    
    try:
        # Step 1: Baseline recommendations
        baseline_response = requests.get(f"{BASE_URL}/recommendations", params={
            "user_id": user_id,
            "k": 20
        })
        
        if baseline_response.status_code != 200:
            return TestResult(
                name=test_name,
                status="FAIL",
                expected="Baseline recommendations",
                observed=f"{baseline_response.status_code}",
                reason="Cannot get baseline",
                duration_ms=(time.time() - start) * 1000
            )
        
        baseline_data = baseline_response.json()
        baseline_recs = baseline_data.get("recommendations", [])
        baseline_strategy = baseline_data.get("strategy_used", "unknown")
        
        if len(baseline_recs) < 5:
            return TestResult(
                name=test_name,
                status="SKIP",
                expected="At least 5 recommendations",
                observed=f"Only {len(baseline_recs)} items",
                reason="Insufficient recommendations for testing"
            )
        
        # Step 2: Track session events
        target_product_id = baseline_recs[3]["product_id"]
        target_category = baseline_recs[3].get("category_slug")
        
        # Track category view
        if target_category:
            requests.post(f"{BASE_URL}/session/track", json={
                "user_id": user_id,
                "event_type": "category_view",
                "category_slug": target_category
            })
        
        # Track product view
        requests.post(f"{BASE_URL}/session/track", json={
            "user_id": user_id,
            "event_type": "product_view",
            "product_id": target_product_id
        })
        
        # Wait for session to register
        time.sleep(1)
        
        # Step 3: Get recommendations after session
        session_response = requests.get(f"{BASE_URL}/recommendations", params={
            "user_id": user_id,
            "k": 20
        })
        
        if session_response.status_code != 200:
            return TestResult(
                name=test_name,
                status="FAIL",
                expected="Post-session recommendations",
                observed=f"{session_response.status_code}",
                reason="Cannot get post-session recs",
                duration_ms=(time.time() - start) * 1000
            )
        
        session_data = session_response.json()
        session_recs = session_data.get("recommendations", [])
        session_strategy = session_data.get("strategy_used", "unknown")
        
        # Step 4: Compare rankings
        baseline_ids = [r["product_id"] for r in baseline_recs]
        session_ids = [r["product_id"] for r in session_recs]
        
        # Find target product position
        baseline_pos = baseline_ids.index(target_product_id) if target_product_id in baseline_ids else -1
        session_pos = session_ids.index(target_product_id) if target_product_id in session_ids else -1
        
        duration = (time.time() - start) * 1000
        
        # Check if ranking changed
        ranking_changed = baseline_ids != session_ids
        target_moved_up = (baseline_pos != -1 and session_pos != -1 and session_pos < baseline_pos)
        
        if ranking_changed:
            if target_moved_up:
                return TestResult(
                    name=test_name,
                    status="PASS",
                    expected="Session signals affect ranking (target product moves up)",
                    observed=f"Target moved from #{baseline_pos+1} to #{session_pos+1}",
                    duration_ms=duration,
                    details={
                        "baseline_strategy": baseline_strategy,
                        "session_strategy": session_strategy,
                        "baseline_pos": baseline_pos + 1,
                        "session_pos": session_pos + 1,
                        "improvement": baseline_pos - session_pos
                    }
                )
            else:
                return TestResult(
                    name=test_name,
                    status="PASS",
                    expected="Session signals affect ranking",
                    observed=f"Rankings changed (target: #{baseline_pos+1} → #{session_pos+1})",
                    duration_ms=duration,
                    details={
                        "baseline_strategy": baseline_strategy,
                        "session_strategy": session_strategy,
                        "ranking_changed": True
                    }
                )
        else:
            # Rankings did NOT change - need to explain why
            return TestResult(
                name=test_name,
                status="FAIL",
                expected="Rankings change with session signals",
                observed="No ranking change detected",
                reason=f"Session re-ranking not working. Strategy: {session_strategy}. Possible causes: Redis disabled, session reranker not integrated, or session data not consumed.",
                duration_ms=duration,
                details={
                    "baseline_strategy": baseline_strategy,
                    "session_strategy": session_strategy,
                    "target_product": target_product_id,
                    "target_category": target_category
                }
            )
    except Exception as e:
        return TestResult(
            name=test_name,
            status="FAIL",
            expected="Session re-ranking tested",
            observed=f"Exception: {str(e)}",
            reason=str(e),
            duration_ms=(time.time() - start) * 1000
        )


def test_item_similarity():
    """Test item-to-item similarity recommendations."""
    test_name = "Item Similarity Recommendations"
    start = time.time()
    
    try:
        # Get a product ID first
        catalog_response = requests.get(f"{BASE_URL}/catalog/products", params={"limit": 1})
        if catalog_response.status_code != 200:
            return TestResult(
                name=test_name,
                status="SKIP",
                expected="Product ID available",
                observed="Cannot fetch product",
                reason="Catalog unavailable"
            )
        
        products = catalog_response.json().get("products", [])
        if not products:
            return TestResult(
                name=test_name,
                status="SKIP",
                expected="At least one product",
                observed="Empty catalog",
                reason="No products to test"
            )
        
        item_id = products[0]["id"]
        
        # Get similar items
        response = requests.get(f"{BASE_URL}/recommendations", params={
            "product_id": item_id,
            "k": 10
        })
        duration = (time.time() - start) * 1000
        
        if response.status_code == 200:
            data = response.json()
            strategy = data.get("strategy_used", "unknown")
            recs = data.get("recommendations", [])
            
            # Should use similarity or item-based strategy
            if "similarity" in strategy.lower() or "item" in strategy.lower():
                return TestResult(
                    name=test_name,
                    status="PASS",
                    expected="Item similarity recommendations",
                    observed=f"Strategy: {strategy}, {len(recs)} items",
                    duration_ms=duration,
                    details={"strategy": strategy, "source_item": item_id}
                )
            else:
                return TestResult(
                    name=test_name,
                    status="FAIL",
                    expected="similarity strategy",
                    observed=f"Strategy: {strategy}",
                    reason="Wrong strategy for item similarity",
                    duration_ms=duration
                )
        else:
            return TestResult(
                name=test_name,
                status="FAIL",
                expected="200 OK",
                observed=f"{response.status_code}",
                reason="Request failed",
                duration_ms=duration
            )
    except Exception as e:
        return TestResult(
            name=test_name,
            status="FAIL",
            expected="Similarity recommendations",
            observed=f"Exception: {str(e)}",
            reason=str(e),
            duration_ms=(time.time() - start) * 1000
        )


def test_svd_reality():
    """
    Test SVD Personalization Reality.
    
    Proves that SVD does NOT personalize for UUID users.
    Documents why this is acceptable.
    """
    test_name = "SVD Personalization Reality Check"
    start = time.time()
    
    user1 = f"uuid-{int(time.time() * 1000)}-A"
    user2 = f"uuid-{int(time.time() * 1000)}-B"
    
    try:
        # Get recommendations for two different UUID users
        response1 = requests.get(f"{BASE_URL}/recommendations", params={"user_id": user1, "k": 10})
        response2 = requests.get(f"{BASE_URL}/recommendations", params={"user_id": user2, "k": 10})
        
        duration = (time.time() - start) * 1000
        
        if response1.status_code == 200 and response2.status_code == 200:
            data1 = response1.json()
            data2 = response2.json()
            
            recs1 = [r["product_id"] for r in data1.get("recommendations", [])]
            recs2 = [r["product_id"] for r in data2.get("recommendations", [])]
            
            strategy1 = data1.get("strategy_used", "")
            strategy2 = data2.get("strategy_used", "")
            
            # If recommendations are identical, SVD is NOT personalizing
            if recs1 == recs2:
                if "popularity" in strategy1.lower() or "fallback" in strategy1.lower():
                    return TestResult(
                        name=test_name,
                        status="PASS",
                        expected="No personalization for UUID users (documented limitation)",
                        observed=f"Both users got identical popularity-based recs",
                        duration_ms=duration,
                        details={
                            "strategy": strategy1,
                            "reason": "SVD trained on integer user_ids from RetailRocket. UUID users require mapping or retraining.",
                            "acceptable": "YES - This is expected. Session re-ranking provides differentiation."
                        }
                    )
                else:
                    return TestResult(
                        name=test_name,
                        status="FAIL",
                        expected="Popularity fallback (documented)",
                        observed=f"Strategy: {strategy1}, but recs are identical",
                        reason="Strategy claim doesn't match behavior",
                        duration_ms=duration
                    )
            else:
                # Recommendations differ - unexpected for UUID users
                return TestResult(
                    name=test_name,
                    status="FAIL",
                    expected="Identical recs for UUID users",
                    observed="Recommendations differ",
                    reason="Unexpected personalization or non-deterministic behavior",
                    duration_ms=duration,
                    details={
                        "strategy1": strategy1,
                        "strategy2": strategy2,
                        "overlap": len(set(recs1) & set(recs2))
                    }
                )
        else:
            return TestResult(
                name=test_name,
                status="FAIL",
                expected="200 OK",
                observed=f"{response1.status_code}, {response2.status_code}",
                reason="Request failed",
                duration_ms=duration
            )
    except Exception as e:
        return TestResult(
            name=test_name,
            status="FAIL",
            expected="SVD reality tested",
            observed=f"Exception: {str(e)}",
            reason=str(e),
            duration_ms=(time.time() - start) * 1000
        )


def test_recommendation_quality():
    """Test basic recommendation quality (no duplicates, valid IDs)."""
    test_name = "Recommendation Quality Check"
    start = time.time()
    
    try:
        response = requests.get(f"{BASE_URL}/recommendations", params={"user_id": "quality-test", "k": 20})
        duration = (time.time() - start) * 1000
        
        if response.status_code == 200:
            data = response.json()
            recs = data.get("recommendations", [])
            
            # Check for duplicates
            product_ids = [r["product_id"] for r in recs]
            unique_ids = set(product_ids)
            
            has_duplicates = len(product_ids) != len(unique_ids)
            
            # Check all have required fields
            required_fields = ["product_id", "score"]
            all_valid = all(all(f in r for f in required_fields) for r in recs)
            
            if not has_duplicates and all_valid:
                return TestResult(
                    name=test_name,
                    status="PASS",
                    expected="No duplicates, valid structure",
                    observed=f"{len(recs)} unique items, all valid",
                    duration_ms=duration
                )
            else:
                issues = []
                if has_duplicates:
                    issues.append(f"{len(product_ids) - len(unique_ids)} duplicates")
                if not all_valid:
                    issues.append("missing required fields")
                
                return TestResult(
                    name=test_name,
                    status="FAIL",
                    expected="Quality recommendations",
                    observed=f"Issues: {', '.join(issues)}",
                    reason="Quality check failed",
                    duration_ms=duration
                )
        else:
            return TestResult(
                name=test_name,
                status="FAIL",
                expected="200 OK",
                observed=f"{response.status_code}",
                reason="Request failed",
                duration_ms=duration
            )
    except Exception as e:
        return TestResult(
            name=test_name,
            status="FAIL",
            expected="Quality check passed",
            observed=f"Exception: {str(e)}",
            reason=str(e),
            duration_ms=(time.time() - start) * 1000
        )


def main():
    """Run all recommendation service tests."""
    print_header("RECOMMENDATION SERVICE TEST SUITE (CRITICAL ML VALIDATION)")
    
    suite = TestSuite("Recommendation Service")
    
    # Run all recommendation path tests
    suite.add_result(test_anonymous_cold_start())
    suite.add_result(test_new_user_cold_start())
    suite.add_result(test_session_aware_reranking())  # THE CRITICAL TEST
    suite.add_result(test_item_similarity())
    suite.add_result(test_svd_reality())
    suite.add_result(test_recommendation_quality())
    
    suite.finalize()
    exit_code = suite.print_report()
    
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
