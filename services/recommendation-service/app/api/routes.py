"""
API routes for Recommendation Service.

Endpoints:
- GET /api/v1/recommendations: Get personalized recommendations
- GET /health: Health check
"""
from fastapi import APIRouter, HTTPException, Query, Depends
from typing import Optional, List, Dict, Any
from uuid import UUID
import asyncio
import time
try:
    import numpy as np
except ImportError:
    np = None
import httpx

from app.api.schemas import (
    RecommendationRequest,
    RecommendationResponse,
    RecommendedProduct,
    HealthResponse,
    SessionTrackRequest,
    SessionTrackResponse
)
from app.models.svd import get_svd_model
from app.models.popularity import get_popularity_model
from app.models.lightgbm_ranker import get_ranker
from app.models.similarity import get_similarity_model
from app.features.loader import get_feature_loader
from app.mapping.latent_mapper import get_latent_mapper
from app.session.reranker import get_session_reranker
from app.personalization.user_preferences import get_user_preference_loader, apply_long_term_boost
from app.decisioning.rules import apply_all_rules
from app.core.config import settings, get_catalog_service_url
from app.core.logging import get_logger, log_request, log_fallback, log_recommendation
from app.inference.client import get_inference_client

logger = get_logger(__name__)
router = APIRouter()


def _safe_endpoint_context(**kwargs: Any) -> Dict[str, Any]:
    """Build a compact log context without empty values."""
    return {key: value for key, value in kwargs.items() if value is not None}


def _log_endpoint_exception(endpoint: str, error: Exception, **context: Any) -> None:
    """Log a full traceback for an endpoint failure."""
    logger.exception("%s failed | context=%s", endpoint, _safe_endpoint_context(**context))


async def fetch_product_metadata_safe(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    base_url: str,
    product_id: UUID,
) -> tuple[UUID, Dict[str, Any], float]:
    """Fetch a single product metadata record with bounded concurrency and graceful fallback."""
    request_url = f"{base_url}/api/v1/catalog/products/{product_id}"
    request_start = time.time()

    async with semaphore:
        try:
            logger.info(
                "Fetching metadata from: %s | base_url=%s | product_id=%s",
                request_url,
                base_url,
                product_id,
            )
            response = await client.get(request_url)
            request_latency_ms = (time.time() - request_start) * 1000

            if response.status_code == 200:
                product_data = response.json()
                category = product_data.get('category', {})
                category_slug = category.get('slug', category.get('name', '').lower().replace(' ', '-'))

                return product_id, {
                    'name': product_data.get('name', ''),
                    'price': product_data.get('price', 0),
                    'category_name': category.get('name', ''),
                    'category_slug': category_slug,
                    'image_url': product_data.get('image_url', ''),
                    'stock_quantity': 10,  # Mock for now
                    'is_deleted': False,
                    'category_id': category.get('id', '')
                }, request_latency_ms

            logger.warning(
                "Failed to fetch product metadata | product_id=%s | http_status=%s | request_url=%s",
                product_id,
                response.status_code,
                request_url,
            )
        except Exception:
            logger.exception(
                "Error fetching product metadata | product_id=%s | request_url=%s",
                product_id,
                request_url,
            )

    request_latency_ms = (time.time() - request_start) * 1000
    return product_id, {
        'name': '',
        'price': 0,
        'stock_quantity': 10,
        'is_deleted': False,
        'category_id': hash(product_id) % 10
    }, request_latency_ms


async def fetch_product_metadata(product_ids: List[UUID]) -> Dict[UUID, Dict[str, Any]]:
    """
    Fetch product metadata from catalog service.
    
    Why needed:
    - Product names and prices for frontend display
    - Stock filtering (stock_quantity)
    - Diversity constraint (category_id)
    - Inactive filtering (is_deleted)
    """
    if not product_ids:
        return {}
    
    try:
        base_url = get_catalog_service_url()
        logger.info("Resolved catalog metadata base URL: %s", base_url)
        hydration_start = time.time()

        # Call catalog service through API gateway
        async with httpx.AsyncClient(timeout=5.0) as client:
            semaphore = asyncio.Semaphore(10)
            tasks = [fetch_product_metadata_safe(client, semaphore, base_url, pid) for pid in product_ids]
            results = await asyncio.gather(*tasks)

            metadata = {pid: payload for pid, payload, _ in results}
            latencies = [latency for _, _, latency in results]
            hydrated_count = sum(1 for payload in metadata.values() if payload.get('name'))
            total_hydration_ms = (time.time() - hydration_start) * 1000
            average_request_latency_ms = sum(latencies) / len(latencies) if latencies else 0.0

            logger.info(
                "Metadata hydration complete | hydrated=%s/%s | total_duration_ms=%.2f | avg_request_latency_ms=%.2f",
                hydrated_count,
                len(product_ids),
                total_hydration_ms,
                average_request_latency_ms,
            )
            return metadata
            
    except Exception as e:
        logger.exception("Failed to fetch product metadata batch")
        # Fallback to mock data
        return {
            pid: {
                'name': '',
                'price': 0,
                'stock_quantity': 10,
                'is_deleted': False,
                'category_id': hash(pid) % 10
            }
            for pid in product_ids
        }


@router.get("/api/v1/recommendations", response_model=RecommendationResponse)
async def get_recommendations(
    user_id: Optional[str] = Query(None, description="User ID for personalized recs (UUID or RetailRocket ID)"),
    product_id: Optional[str] = Query(None, description="Product ID for similar items (UUID or RetailRocket ID)"),
    k: int = Query(10, ge=1, le=50, description="Number of recommendations"),
    include_metadata: bool = Query(False, description="Include explainability metadata")
):
    """
    Get personalized recommendations.
    
    Pipeline:
    1. Candidate Generation (SVD / Similarity / Popularity)
    2. Feature Assembly
    3. Ranking (LightGBM)
    4. Latent → Catalog Mapping
    5. Decisioning Rules
    6. Top-K Selection
    
    Returns:
    - Ranked list of product UUIDs
    - Strategy used
    - Metadata (optional)
    """
    start_time = time.time()
    logger.info(
        "Recommendation request: user_id=%s, product_id=%s, k=%s, include_metadata=%s",
        user_id,
        product_id,
        k,
        include_metadata,
    )
    
    # Normalize inputs (handles Query default objects if called directly in unit tests)
    clean_user_id = str(user_id) if isinstance(user_id, (str, int)) and not hasattr(user_id, "default") else None
    clean_product_id = product_id if isinstance(product_id, (str, int, UUID)) and not hasattr(product_id, "default") else None

    user_id = clean_user_id
    product_id = clean_product_id
    
    if user_id is None and product_id is None:
        logger.info("Guest recommendation request received (no user_id or product_id) | using popularity baseline")
    
    try:
        logger.info("Resolved catalog metadata base URL: %s", get_catalog_service_url())

        # Step 0: Check External ML Inference boundary
        external_ml_candidates = None
        if settings.ml_inference_enabled and settings.ml_inference_url:
            inference_client = get_inference_client()
            try:
                retailrocket_item_id = None
                if product_id is not None:
                    if isinstance(product_id, (int, str)) and str(product_id).isdigit():
                        retailrocket_item_id = int(product_id)
                        logger.info("Using direct numeric item ID for external ML: %s", retailrocket_item_id)
                    else:
                        mapper = get_latent_mapper()
                        retailrocket_item_id = await mapper.get_latent_id_for_product(product_id)
                        logger.info(
                            "Reverse-mapped product UUID %s -> RetailRocket ID %s for external ML",
                            product_id,
                            retailrocket_item_id
                        )

                ext_resp = await inference_client.infer(
                    user_id=str(user_id) if user_id is not None else None,
                    item_id=retailrocket_item_id,
                    k=settings.candidate_pool_size,
                    model_version=getattr(settings, 'model_version', None)
                )

                if ext_resp and ext_resp.status == "success" and ext_resp.items:
                    ranked_items = [(item.item_id, item.score) for item in ext_resp.items]
                    retailrocket_ids = [item_id for item_id, _ in ranked_items]
                    logger.info(
                        "External ML inference succeeded | strategy=%s | count=%d",
                        ext_resp.strategy_used,
                        len(ranked_items)
                    )
                    
                    # Verify candidate IDs have valid catalog mappings
                    mapper = get_latent_mapper()
                    catalog_mapping = await mapper.map_to_catalog(
                        retailrocket_ids,
                        confidence_threshold=settings.confidence_threshold,
                        preserve_ids=True
                    )
                    
                    if catalog_mapping:
                        logger.info(
                            "External ML candidates successfully mapped to %d catalog products",
                            len(catalog_mapping)
                        )
                        external_ml_candidates = (ext_resp.strategy_used, ranked_items, catalog_mapping)
                    else:
                        logger.warning(
                            "External ML inference returned %d candidates, but none mapped to catalog products in database. Falling back to local pipeline.",
                            len(retailrocket_ids)
                        )
                        log_fallback(logger, "external_ml_unmapped_candidates", "local_pipeline")
                else:
                    status_reason = ext_resp.status if ext_resp else "no_response"
                    logger.info(
                        "External ML inference returned status='%s', falling back to local pipeline",
                        status_reason
                    )
                    log_fallback(logger, f"external_ml_{status_reason}", "local_pipeline")
            except Exception as e:
                logger.exception("External ML inference exception, falling back to local pipeline: %s", e)
                log_fallback(logger, "external_ml_exception", "local_pipeline")

        if external_ml_candidates is not None:
            strategy_used, ranked_items_with_scores, catalog_mapping = external_ml_candidates
            retailrocket_ids = [item_id for item_id, _ in ranked_items_with_scores]
        else:
            catalog_mapping = None
            # Step 1: Candidate Generation (Local Pipeline)
            candidate_result = await generate_candidates(
                user_id=user_id,
                product_id=product_id,
                k=settings.candidate_pool_size
            )
            
            # Handle different return formats
            if len(candidate_result) == 3:
                # Category-based similarity returns (strategy, uuids, True)
                strategy_used, catalog_uuids, skip_mapping = candidate_result
                logger.info(f"Candidate generation (direct UUIDs): strategy={strategy_used}, count={len(catalog_uuids) if catalog_uuids else 0}")
                
                if not catalog_uuids:
                    logger.warning(
                        "No candidates generated, returning empty recommendations | strategy=%s | user_id=%s | product_id=%s | empty_candidates=True",
                        strategy_used,
                        user_id,
                        product_id,
                    )
                    return RecommendationResponse(
                        recommendations=[],
                        strategy_used=strategy_used,
                        total_candidates=0,
                        total_returned=0
                    )
                
                # Skip feature assembly, ranking, and mapping - go straight to metadata
                product_metadata = await fetch_product_metadata(catalog_uuids)
                
                # Apply decisioning rules
                valid_uuids = await apply_all_rules(catalog_uuids, product_metadata)
                final_uuids = valid_uuids[:k]
                final_scores = [1.0 - (rank * 0.05) for rank in range(len(final_uuids))]

                # Step 7.5: Long-Term Personalization (before session reranking)
                lt_meta = None
                if user_id and settings.long_term_personalization_enabled:
                    try:
                        pref_loader = get_user_preference_loader()
                        preferences = await pref_loader.get_preferences(str(user_id))
                        if not preferences.is_empty():
                            final_uuids, final_scores, lt_meta = apply_long_term_boost(
                                candidates=final_uuids,
                                scores=final_scores,
                                product_metadata=product_metadata,
                                preferences=preferences,
                            )
                            logger.info(
                                "Long-term personalization applied (category_similarity path) | user=%s | boosted=%s",
                                user_id,
                                lt_meta.get('items_boosted', 0),
                            )
                    except Exception:
                        logger.exception(
                            "Long-term personalization failed (category_similarity path) | user_id=%s",
                            user_id,
                        )

                # Step 8: Session Re-Ranking if user_id/session is provided
                session_meta = None
                if user_id and settings.redis_enabled:
                    try:
                        reranker = await get_session_reranker(settings.redis_url)
                        if reranker.enabled:
                            reranked_candidates, reranked_scores, session_meta = await reranker.apply_session_boost(
                                user_id=str(user_id),
                                candidates=final_uuids,
                                scores=final_scores,
                                product_metadata=product_metadata
                            )
                            final_uuids = reranked_candidates
                            final_scores = reranked_scores
                    except Exception:
                        logger.exception("Session re-ranking failed in category similarity path | user_id=%s", user_id)

                # Build boost maps for response metadata
                session_boost_map = session_meta.get('boost_map', {}) if session_meta else {}
                lt_boost_map = lt_meta.get('boost_map', {}) if lt_meta else {}

                # Build recommendations
                recommendations = []
                for rank, (pid, score) in enumerate(zip(final_uuids, final_scores)):
                    s_info = session_boost_map.get(pid) or session_boost_map.get(str(pid)) or {}
                    lt_info = lt_boost_map.get(pid) or lt_boost_map.get(str(pid)) or {}
                    is_session_boosted = s_info.get('is_boosted', False) or (s_info.get('boost', 0.0) > 0)
                    is_lt_boosted = lt_info.get('is_boosted', False)
                    reasons = s_info.get('reasons', [])

                    if is_session_boosted:
                        reason = f"Boosted by session intent ({', '.join(reasons)})"
                    elif is_lt_boosted:
                        reason = f"Boosted by long-term preference ({lt_info.get('reason', '')})"
                    elif include_metadata:
                        reason = f"Recommended via {strategy_used}"
                    else:
                        reason = None

                    recommendations.append(
                        RecommendedProduct(
                            product_id=pid,
                            score=score,
                            rank=rank + 1,
                            name=product_metadata.get(pid, {}).get('name'),
                            price=product_metadata.get(pid, {}).get('price'),
                            category_name=product_metadata.get(pid, {}).get('category_name'),
                            category_slug=product_metadata.get(pid, {}).get('category_slug'),
                            image_url=product_metadata.get(pid, {}).get('image_url'),
                            reason=reason,
                            confidence=1.0 if include_metadata else None,
                            session_boosted=True if is_session_boosted else None,
                            long_term_boosted=True if is_lt_boosted else None,
                        )
                    )

                latency_ms = (time.time() - start_time) * 1000
                log_request(
                    logger,
                    "/api/v1/recommendations",
                    {"user_id": str(user_id), "product_id": str(product_id), "k": k},
                    latency_ms
                )

                # Log structured recommendation event for monitoring
                log_recommendation(
                    logger=logger,
                    user_id=user_id,
                    product_id=product_id,
                    strategy_used=strategy_used,
                    model_version=getattr(settings, 'model_version', 'unknown'),
                    recommended_items=final_uuids,
                    latency_ms=latency_ms
                )

                return RecommendationResponse(
                    recommendations=recommendations,
                    strategy_used=strategy_used,
                    total_candidates=len(catalog_uuids),
                    total_returned=len(recommendations),
                    session_reranking=session_meta,
                    long_term_personalization=lt_meta,
                )
            else:
                # Normal flow: (strategy, retailrocket_ids)
                strategy_used, candidate_data = candidate_result
                
                # Normalize candidate data: can be List[int] or List[(int, float)]
                # Convert to uniform format: List[(int, float)]
                if candidate_data and isinstance(candidate_data[0], tuple):
                    # Already has scores: [(id, score), ...]
                    retailrocket_ids_with_scores = candidate_data
                    logger.info(f"Candidates include scores (from popularity)")
                else:
                    # IDs only: [id, id, ...] - assign descending scores
                    retailrocket_ids_with_scores = [
                        (item_id, 1.0 - (i * 0.01))
                        for i, item_id in enumerate(candidate_data)
                    ]
                    logger.info(f"Candidates without scores, assigned descending scores (1.0 to {1.0 - (len(candidate_data) * 0.01):.2f})")
                
                # Extract IDs for feature assembly
                retailrocket_ids = [item_id for item_id, _ in retailrocket_ids_with_scores]
            
            logger.info(f"Candidate generation complete: strategy={strategy_used}, count={len(retailrocket_ids) if retailrocket_ids else 0}")
            
            if not retailrocket_ids:
                logger.warning(
                    "No candidates generated, returning empty recommendations | strategy=%s | user_id=%s | product_id=%s | empty_candidates=True",
                    strategy_used,
                    user_id,
                    product_id,
                )
                return RecommendationResponse(
                    recommendations=[],
                    strategy_used=strategy_used,
                    total_candidates=0,
                    total_returned=0
                )
            
            logger.debug(f"Generated {len(retailrocket_ids)} candidates using {strategy_used}")
            
            ranked_items_with_scores = retailrocket_ids_with_scores

            if settings.disable_feature_tables:
                logger.warning("LightGBM ranking skipped because feature tables are disabled.")
                strategy_used = f"{strategy_used}_no_ranking"
            else:
                # Step 2: Feature Assembly
                logger.info(f"Starting feature assembly for {len(retailrocket_ids)} items")
                feature_loader = get_feature_loader()
                features_df = feature_loader.assemble_features(
                    user_id=user_id,
                    retailrocket_item_ids=retailrocket_ids
                )
                logger.info(f"Feature assembly complete: shape={features_df.shape if features_df is not None else 'None'}")

                # Step 3: STAGE 2 - RANKING WITH LIGHTGBM (Precision Layer)
                logger.info("Starting LightGBM ranking (Stage 2 - Precision Layer)")

                ranker = get_ranker()
                if not ranker.is_available() and settings.enable_lightgbm_ranking:
                    try:
                        ranker.load()
                        logger.info("LightGBM model loaded successfully")
                    except Exception as e:
                        logger.exception("Failed to load LightGBM model")
                        settings.enable_lightgbm_ranking = False

                logger.info(f"LightGBM status: is_available={ranker.is_available()}, enabled={settings.enable_lightgbm_ranking}")
                if ranker.is_available() and settings.enable_lightgbm_ranking:
                    try:
                        scores = ranker.predict(features_df)
                        logger.info(f"Raw scores shape: {scores.shape} | dtype: {scores.dtype}")
                        logger.info(f"Score statistics: mean={scores.mean():.4f} | std={scores.std():.4f} | min={scores.min():.4f} | max={scores.max():.4f}")
                        logger.info(f"Unique score count: {len(np.unique(scores))} out of {len(scores)}")
                        logger.info(f"First 5 raw scores: {scores[:5].tolist()}")
                        logger.info(f"Last 5 raw scores: {scores[-5:].tolist()}")
                        
                        # Sort by score descending - sort both IDs and scores together
                        sorted_indices = scores.argsort()[::-1]
                        sorted_scores = scores[sorted_indices]
                        logger.info(f"Top 5 sorted scores: {sorted_scores[:5].tolist()}")
                        logger.info(f"Bottom 5 sorted scores: {sorted_scores[-5:].tolist()}")
                        
                        ranked_items_with_scores = [
                            (retailrocket_ids[i], float(sorted_scores[idx]))
                            for idx, i in enumerate(sorted_indices)
                        ]
                        logger.info(f"LightGBM ranking complete")
                        logger.info(f"Ranked items sample (first 5): {ranked_items_with_scores[:5]}")
                        logger.info(f"Ranked items sample (last 5): {ranked_items_with_scores[-5:]}")
                        
                        # Update strategy name to reflect two-stage pipeline
                        if strategy_used == "svd":
                            strategy_used = "two_stage_svd_lgbm"
                        elif strategy_used == "item_similarity":
                            strategy_used = "two_stage_item_sim_lgbm"
                        elif strategy_used == "popularity":
                            strategy_used = "popularity_fallback"
                            
                    except Exception as e:
                        logger.exception(
                            "LightGBM ranking failed, using original candidate scores | user_id=%s | product_id=%s | candidate_count=%s",
                            user_id,
                            product_id,
                            len(retailrocket_ids),
                        )
                        log_fallback(logger, "lightgbm_failure", "candidate_order")
                        # Fallback: use original scores from candidate generation
                        ranked_items_with_scores = retailrocket_ids_with_scores
                        strategy_used = f"{strategy_used}_no_ranking"
                else:
                    logger.info("LightGBM disabled or unavailable, using original candidate scores")
                    # Use original scores from candidate generation (preserves popularity scores)
                    ranked_items_with_scores = retailrocket_ids_with_scores
                    strategy_used = f"{strategy_used}_no_ranking"

        
        # Extract just IDs for mapping (scores preserved for response)
        retailrocket_ids = [item_id for item_id, _ in ranked_items_with_scores]
        # scores_dict: map retailrocket_id (int) -> score (float)
        scores_dict = {int(item_id): score for item_id, score in ranked_items_with_scores}
        logger.info(f"Created scores_dict with {len(scores_dict)} entries | Sample: {list(scores_dict.items())[:3]}")
        
        # Step 4: Latent → Catalog Mapping (PRESERVE SCORES)
        if catalog_mapping is None:
            logger.info(f"About to call mapper with {len(retailrocket_ids)} IDs")
            mapper = get_latent_mapper()
            catalog_mapping = await mapper.map_to_catalog(
                retailrocket_ids,
                confidence_threshold=settings.confidence_threshold,
                preserve_ids=True  # Returns [(UUID, retailrocket_id), ...]
            )
            logger.info(f"Mapper returned {len(catalog_mapping)} catalog mappings")
        
        if not catalog_mapping:
            logger.warning(
                "No catalog mappings found, returning empty recommendations | candidate_count=%s | threshold=%s | mappings_found=False",
                len(retailrocket_ids),
                settings.confidence_threshold,
            )
            return RecommendationResponse(
                recommendations=[],
                strategy_used=strategy_used,
                total_candidates=len(retailrocket_ids),
                total_returned=0
            )
        
        # Build product_scores list with ACTUAL LightGBM scores from scores_dict
        # NOTE: Ensure rr_id is int for lookup (scores_dict has int keys)
        product_scores = [
            (uuid, scores_dict.get(int(rr_id), 0.0))
            for uuid, rr_id in catalog_mapping
        ]
        logger.info(f"Product scores built: {product_scores}")
        
        logger.debug(f"Mapped to {len(product_scores)} catalog products with preserved scores")
        
        # Step 5: Fetch Product Metadata
        product_ids_only = [pid for pid, _ in product_scores]
        product_metadata = await fetch_product_metadata(product_ids_only)
        
        # Step 6: Apply Decisioning Rules
        valid_pids = set(await apply_all_rules(product_ids_only, product_metadata))
        filtered_products_with_scores = [
            (pid, score)
            for pid, score in product_scores
            if pid in valid_pids
        ]
        
        # Step 7: Top-K Selection
        final_products_with_scores = filtered_products_with_scores[:k]

        # Step 7.5: Long-Term Personalization (before session reranking)
        lt_meta = None
        if user_id and settings.long_term_personalization_enabled:
            try:
                pref_loader = get_user_preference_loader()
                preferences = await pref_loader.get_preferences(str(user_id))
                if not preferences.is_empty():
                    lt_candidates, lt_scores, lt_meta = apply_long_term_boost(
                        candidates=[pid for pid, _ in final_products_with_scores],
                        scores=[score for _, score in final_products_with_scores],
                        product_metadata=product_metadata,
                        preferences=preferences,
                    )
                    final_products_with_scores = list(zip(lt_candidates, lt_scores))
                    logger.info(
                        "Long-term personalization applied | user=%s | boosted=%s | source=%s",
                        user_id,
                        lt_meta.get('items_boosted', 0),
                        lt_meta.get('preferences_source', 'none'),
                    )
            except Exception:
                logger.exception(
                    "Long-term personalization failed | user_id=%s",
                    user_id,
                )

        # Step 8: Apply Session Re-Ranking (if Redis enabled)
        session_meta = None
        if user_id and settings.redis_enabled:
            try:
                reranker = await get_session_reranker(settings.redis_url)
                if reranker.enabled:
                    logger.info("Applying session-aware re-ranking...")
                    reranked_candidates, reranked_scores, session_meta = await reranker.apply_session_boost(
                        user_id=str(user_id),
                        candidates=[pid for pid, _ in final_products_with_scores],
                        scores=[score for _, score in final_products_with_scores],
                        product_metadata=product_metadata
                    )
                    final_products_with_scores = list(zip(reranked_candidates, reranked_scores))
                    logger.info(f"Session re-ranking applied: {session_meta}")
            except Exception:
                logger.exception(
                    "Session re-ranking failed, using original ranking | user_id=%s | candidate_count=%s",
                    user_id,
                    len(final_products_with_scores),
                )

        # Build boost maps for response metadata
        session_boost_map = session_meta.get('boost_map', {}) if session_meta else {}
        lt_boost_map = lt_meta.get('boost_map', {}) if lt_meta else {}

        # Build response with real LightGBM scores and product metadata
        recommendations = []
        for rank, (pid, score) in enumerate(final_products_with_scores):
            s_info = session_boost_map.get(pid) or session_boost_map.get(str(pid)) or {}
            lt_info = lt_boost_map.get(pid) or lt_boost_map.get(str(pid)) or {}
            is_session_boosted = s_info.get('is_boosted', False) or (s_info.get('boost', 0.0) > 0)
            is_lt_boosted = lt_info.get('is_boosted', False)
            reasons = s_info.get('reasons', [])

            if is_session_boosted:
                reason = f"Boosted by session intent ({', '.join(reasons)})"
            elif is_lt_boosted:
                reason = f"Boosted by long-term preference ({lt_info.get('reason', '')})"
            elif include_metadata:
                reason = f"Recommended via {strategy_used}"
            else:
                reason = None

            recommendations.append(
                RecommendedProduct(
                    product_id=pid,
                    score=score,  # Use actual LightGBM scores
                    rank=rank + 1,
                    name=product_metadata.get(pid, {}).get('name'),
                    price=product_metadata.get(pid, {}).get('price'),
                    category_name=product_metadata.get(pid, {}).get('category_name'),
                    category_slug=product_metadata.get(pid, {}).get('category_slug'),
                    image_url=product_metadata.get(pid, {}).get('image_url'),
                    reason=reason,
                    confidence=0.85 if include_metadata else None,
                    session_boosted=True if is_session_boosted else None,
                    long_term_boosted=True if is_lt_boosted else None,
                )
            )

        latency_ms = (time.time() - start_time) * 1000
        log_request(
            logger,
            "/api/v1/recommendations",
            {"user_id": str(user_id), "product_id": str(product_id), "k": k},
            latency_ms
        )

        # Log structured recommendation event for monitoring
        log_recommendation(
            logger=logger,
            user_id=user_id,
            product_id=product_id,
            strategy_used=strategy_used,
            model_version=getattr(settings, 'model_version', 'unknown'),
            recommended_items=[pid for pid, _ in final_products_with_scores],
            latency_ms=latency_ms
        )

        return RecommendationResponse(
            recommendations=recommendations,
            strategy_used=strategy_used,
            total_candidates=len(retailrocket_ids),
            total_returned=len(recommendations),
            session_reranking=session_meta,
            long_term_personalization=lt_meta,
        )
    
    except HTTPException:
        raise
    except Exception as e:
        _log_endpoint_exception(
            "recommendations",
            e,
            user_id=user_id,
            product_id=str(product_id) if product_id else None,
            k=k,
            include_metadata=include_metadata,
        )
        raise HTTPException(status_code=500, detail="Internal server error")


async def generate_candidates(
    user_id: Optional[str],
    product_id: Optional[UUID],
    k: int
) -> tuple[str, List[int]]:
    """
    STAGE 1: CANDIDATE GENERATION (Recall Layer)
    
    Generate candidate items using one of three strategies.
    
    Strategy priority:
    1. Item-item similarity (if product_id provided) - ACTIVATED
    2. User-based SVD (if user_id known) - ACTIVATED
    3. Popularity baseline (cold start fallback)
    
    Why this order:
    - Product context is strongest signal (user looking at specific item)
    - User history second strongest (personalization)
    - Popularity is universal fallback (always works)
    
    Returns:
        (strategy_name, retailrocket_item_ids)
    """
    # Strategy 1: Product-based similarity (ACTIVATED)
    if product_id is not None:
        logger.info(f"Product-based recommendations requested for {product_id}")

        # Try to get product metadata first to extract category and use category-based similarity
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                base_url = get_catalog_service_url()
                request_url = f"{base_url}/api/v1/catalog/products/{product_id}"
                logger.info(
                    "Fetching metadata from: %s | base_url=%s | product_id=%s",
                    request_url,
                    base_url,
                    product_id,
                )
                response = await client.get(request_url)
                if response.status_code == 200:
                    product_data = response.json()
                    category_id = product_data.get('category', {}).get('id') if isinstance(product_data.get('category'), dict) else None
                    if not category_id and 'category_id' in product_data:
                        category_id = product_data['category_id']
                    
                    if category_id:
                        logger.info(f"Product {product_id} belongs to category {category_id}, using category-based recommendations")
                        # Get products from same category as fallback
                        category_request_url = f"{base_url}/api/v1/catalog/products"
                        logger.info(
                            "Fetching category products from: %s | base_url=%s | category_id=%s",
                            category_request_url,
                            base_url,
                            category_id,
                        )
                        category_response = await client.get(
                            category_request_url,
                            params={"category_id": category_id, "per_page": k * 3}  # Get more than needed
                        )
                        if category_response.status_code == 200:
                            category_products = category_response.json().get('products', [])
                            # Extract UUIDs, filter out the current product
                            similar_uuids = [
                                UUID(p['id']) for p in category_products 
                                if p['id'] != str(product_id)
                            ][:k]
                            
                            if similar_uuids:
                                logger.info(f"Found {len(similar_uuids)} products in same category")
                                # Return direct UUIDs bypassing latent mapping
                                return ("category_similarity", similar_uuids, True)
        except Exception as e:
            logger.exception("Failed to fetch category for product-based recommendation | product_id=%s: %s", product_id, e)
        
        if settings.disable_similarity_model:
            logger.info("Local similarity model disabled on deployment, falling back to popularity")
            popularity_model = get_popularity_model()
            if not popularity_model.is_available():
                popularity_model.load()
            mapper = get_latent_mapper()
            valid_ids = await mapper.get_valid_latent_ids()
            return ("popularity", popularity_model.get_top_k(k, valid_ids=valid_ids))
        
        # Local similarity model attempt
        try:
            if isinstance(product_id, (int, str)) and str(product_id).isdigit():
                retailrocket_id = int(product_id)
            else:
                mapper = get_latent_mapper()
                retailrocket_id = await mapper.get_latent_id_for_product(product_id)
            
            if retailrocket_id:
                similarity_model = get_similarity_model()
                if not similarity_model.is_available():
                    try:
                        similarity_model.load()
                    except Exception as e:
                        logger.exception(
                            "Failed to load similarity model | product_id=%s | retailrocket_id=%s",
                            product_id,
                            retailrocket_id,
                        )
                        log_fallback(logger, "similarity_load_failed", "popularity")
                        popularity_model = get_popularity_model()
                        if not popularity_model.is_available():
                            popularity_model.load()
                        mapper = get_latent_mapper()
                        valid_ids = await mapper.get_valid_latent_ids()
                        return ("popularity", popularity_model.get_top_k(k, valid_ids=valid_ids))
                
                similar_items = similarity_model.get_similar_items(retailrocket_id, k)
                if similar_items:
                    logger.info(f"Item-similarity generated {len(similar_items)} candidates for item {retailrocket_id}")
                    return ("item_similarity", similar_items)  # Will be converted to two_stage in main handler
                else:
                    logger.info(f"Item {retailrocket_id} not in similarity matrix, falling back to popularity")
                    log_fallback(logger, "item_not_in_similarity", "popularity")
        except Exception:
            logger.exception(
                "Similarity lookup failed | product_id=%s | retailrocket_id=%s",
                product_id,
                retailrocket_id if 'retailrocket_id' in locals() else None,
            )
            log_fallback(logger, "similarity_error", "popularity")
        
        # Fallback to popularity for product-based queries
        popularity_model = get_popularity_model()
        if not popularity_model.is_available():
            popularity_model.load()
        return ("popularity", popularity_model.get_top_k(k))
    
    # Strategy 2: User-based SVD (ACTIVATED)
    if user_id is not None and settings.enable_svd:
        logger.info(f"User-based recommendations requested for {user_id}")
        svd_model = get_svd_model()
        
        # Load SVD model if not already loaded
        if not svd_model.is_available():
            try:
                svd_model.load()
                logger.info("SVD model loaded successfully")
            except Exception as e:
                logger.exception("Failed to load SVD model | user_id=%s", user_id)
                log_fallback(logger, "svd_load_failed", "popularity")
                popularity_model = get_popularity_model()
                if not popularity_model.is_available():
                    popularity_model.load()
                mapper = get_latent_mapper()
                valid_ids = await mapper.get_valid_latent_ids()
                return ("popularity", popularity_model.get_top_k(k, valid_ids=valid_ids))
        
        # Generate candidates using SVD
        candidates = svd_model.get_candidates(user_id, k)
        if candidates:
            logger.info(f"SVD generated {len(candidates)} candidates for user {user_id}")
            return ("svd", candidates)  # Will be converted to two_stage in main handler
        else:
            logger.info(f"User {user_id} not in SVD model (cold start), falling back to popularity")
            log_fallback(logger, "unknown_user", "popularity")
    
    # Strategy 3: Popularity baseline (cold start fallback)
    logger.info("Using popularity baseline (cold start or fallback)")
    popularity_model = get_popularity_model()
    if not popularity_model.is_available():
        popularity_model.load()
    
    # Fetch valid latent IDs that have catalog mappings
    mapper = get_latent_mapper()
    valid_ids = await mapper.get_valid_latent_ids()
    logger.info(f"Fetched {len(valid_ids)} valid mapped latent IDs for popularity filtering")
    
    return ("popularity", popularity_model.get_top_k(k, valid_ids=valid_ids))


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Health check endpoint.
    
    Checks:
    - Service is running
    - Models loaded
    - Database connected
    """
    try:
        # Check models
        ranker = get_ranker()
        svd = get_svd_model()
        similarity = get_similarity_model()
        popularity = get_popularity_model()
        
        models_loaded = {
            "lightgbm": ranker.is_available(),
            "svd": svd.is_available(),
            "similarity": similarity.is_available(),
            "popularity": popularity.is_available()
        }
        
        # Check database
        mapper = get_latent_mapper()
        if mapper.pool is None:
            await mapper.connect()
        db_connected = mapper.pool is not None
        
        # Check external ML inference status
        ml_inference_status = "disabled"
        if settings.ml_inference_enabled and settings.ml_inference_url:
            inference_client = get_inference_client()
            is_ext_healthy = await inference_client.health_check()
            ml_inference_status = "connected" if is_ext_healthy else "unreachable"

        return HealthResponse(
            status="healthy",
            models_loaded=models_loaded,
            database_connected=db_connected,
            ml_inference_status=ml_inference_status
        )
    
    except Exception:
        logger.exception("Health check failed")
        return HealthResponse(
            status="unhealthy",
            models_loaded={},
            database_connected=False,
            ml_inference_status="error"
        )


@router.post("/api/v1/session/track", response_model=SessionTrackResponse)
async def track_session_event(request: SessionTrackRequest):
    """
    Track user session event for intent-aware recommendations.
    
    Events:
    - category_view: User browsing a category
    - product_view: User viewing a product
    
    Signals are used for session-aware re-ranking.
    """
    try:
        reranker = await get_session_reranker(settings.redis_url if settings.redis_enabled else None)
        logger.info(
            "Session tracking request received | user_id=%s | event_type=%s | category_slug=%s | product_id=%s",
            request.user_id,
            request.event_type,
            request.category_slug,
            request.product_id,
        )
        
        if not reranker.enabled:
            logger.warning(
                "Session tracking disabled | user_id=%s | event_type=%s",
                request.user_id,
                request.event_type,
            )
            return SessionTrackResponse(
                success=False,
                message="Session tracking disabled (Redis not available)"
            )
        
        if request.event_type == "category_view":
            if not request.category_slug:
                raise HTTPException(status_code=400, detail="category_slug required for category_view")
            
            await reranker.track_category_view(request.user_id, request.category_slug)
            logger.info(
                "Session category view tracked | user_id=%s | category_slug=%s",
                request.user_id,
                request.category_slug,
            )
            return SessionTrackResponse(
                success=True,
                message=f"Tracked category view: {request.category_slug}"
            )
        
        elif request.event_type == "product_view":
            if not request.product_id:
                raise HTTPException(status_code=400, detail="product_id required for product_view")
            
            category_slug = request.category_slug
            if not category_slug:
                try:
                    prod_meta = await fetch_product_metadata([request.product_id])
                    if request.product_id in prod_meta:
                        category_slug = prod_meta[request.product_id].get('category_slug') or prod_meta[request.product_id].get('category_name')
                except Exception:
                    pass

            await reranker.track_product_view(
                request.user_id,
                request.product_id,
                category_slug=category_slug
            )
            logger.info(
                "Session product view tracked | user_id=%s | product_id=%s | category_slug=%s",
                request.user_id,
                request.product_id,
                category_slug,
            )
            return SessionTrackResponse(
                success=True,
                message=f"Tracked product view: {request.product_id}"
            )
        
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid event_type: {request.event_type}"
            )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Session tracking failed | user_id=%s | event_type=%s | category_slug=%s | product_id=%s",
            request.user_id,
            request.event_type,
            request.category_slug,
            request.product_id,
        )
        return SessionTrackResponse(
            success=False,
            message=f"Tracking failed: {str(e)}"
        )
