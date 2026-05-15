"""
API routes for Recommendation Service.

Endpoints:
- GET /api/v1/recommendations: Get personalized recommendations
- GET /health: Health check
"""
from fastapi import APIRouter, HTTPException, Query, Depends
from typing import Optional, List, Dict, Any
from uuid import UUID
import time
import numpy as np
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
from app.decisioning.rules import apply_all_rules
from app.core.config import settings
from app.core.logging import get_logger, log_request, log_fallback, log_recommendation

logger = get_logger(__name__)
router = APIRouter()


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
        # Call catalog service through API gateway
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Fetch products individually (catalog doesn't have batch endpoint)
            metadata = {}
            for pid in product_ids:
                try:
                    response = await client.get(
                        f"{settings.catalog_service_url}/api/v1/catalog/products/{pid}"
                    )
                    if response.status_code == 200:
                        product_data = response.json()
                        # Extract category slug from category object
                        category = product_data.get('category', {})
                        category_slug = category.get('slug', category.get('name', '').lower().replace(' ', '-'))
                        
                        metadata[pid] = {
                            'name': product_data.get('name', ''),
                            'price': product_data.get('price', 0),
                            'category_name': category.get('name', ''),
                            'category_slug': category_slug,
                            'image_url': product_data.get('image_url', ''),
                            'stock_quantity': 10,  # Mock for now
                            'is_deleted': False,
                            'category_id': category.get('id', '')
                        }
                    else:
                        logger.warning(f"Failed to fetch product {pid}: HTTP {response.status_code}")
                except Exception as e:
                    logger.warning(f"Error fetching product {pid}: {e}")
                    continue
            
            logger.info(f"Fetched metadata for {len(metadata)}/{len(product_ids)} products")
            return metadata
            
    except Exception as e:
        logger.error(f"Failed to fetch product metadata: {e}")
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
    logger.info(f"Recommendation request: user_id={user_id}, product_id={product_id}, k={k}")
    
    # Validation: At least one of user_id or product_id required
    if user_id is None and product_id is None:
        raise HTTPException(
            status_code=400,
            detail="At least one of user_id or product_id must be provided"
        )
    
    try:
        # Step 1: Candidate Generation
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
                logger.warning("No candidates generated, returning empty recommendations")
                return RecommendationResponse(
                    recommendations=[],
                    strategy_used=strategy_used,
                    total_candidates=0,
                    total_returned=0
                )
            
            # Skip feature assembly, ranking, and mapping - go straight to metadata
            product_metadata = await fetch_product_metadata(catalog_uuids[:k])
            
            # Build recommendations with mock scores
            recommendations = [
                RecommendedProduct(
                    product_id=pid,
                    score=1.0 - (rank * 0.1),  # Descending scores
                    rank=rank + 1,
                    name=product_metadata.get(pid, {}).get('name'),
                    price=product_metadata.get(pid, {}).get('price'),
                    category_name=product_metadata.get(pid, {}).get('category_name'),
                    image_url=product_metadata.get(pid, {}).get('image_url'),
                    reason=f"Recommended via {strategy_used}" if include_metadata else None,
                    confidence=1.0 if include_metadata else None
                )
                for rank, pid in enumerate(catalog_uuids[:k])
            ]
            
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
                recommended_items=catalog_uuids[:k],
                latency_ms=latency_ms
            )
            
            return RecommendationResponse(
                recommendations=recommendations,
                strategy_used=strategy_used,
                total_candidates=len(catalog_uuids),
                total_returned=len(recommendations)
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
            logger.warning("No candidates generated, returning empty recommendations")
            return RecommendationResponse(
                recommendations=[],
                strategy_used=strategy_used,
                total_candidates=0,
                total_returned=0
            )
        
        logger.debug(f"Generated {len(retailrocket_ids)} candidates using {strategy_used}")
        
        # Step 2: Feature Assembly
        logger.info(f"Starting feature assembly for {len(retailrocket_ids)} items")
        feature_loader = get_feature_loader()
        features_df = feature_loader.assemble_features(
            user_id=user_id,
            retailrocket_item_ids=retailrocket_ids
        )
        logger.info(f"Feature assembly complete: shape={features_df.shape if features_df is not None else 'None'}")
        
        # Step 3: STAGE 2 - RANKING WITH LIGHTGBM (Precision Layer)
        # Why two-stage pipeline:
        # - Stage 1 (Recall): Fast generation of ~100 candidates
        # - Stage 2 (Precision): Expensive ML ranking of candidates
        # - Separates concerns: recall vs precision
        logger.info("Starting LightGBM ranking (Stage 2 - Precision Layer)")
        
        ranker = get_ranker()
        if not ranker.is_available() and settings.enable_lightgbm_ranking:
            try:
                ranker.load()
                logger.info("LightGBM model loaded successfully")
            except Exception as e:
                logger.warning(f"Failed to load LightGBM model: {e}")
                settings.enable_lightgbm_ranking = False
        
        # Apply LightGBM ranking
        ranked_items_with_scores = []
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
                sorted_scores = scores[sorted_indices]  # Apply sorting to scores too!
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
                logger.error(f"LightGBM ranking failed, using original candidate scores: {e}")
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
        logger.info(f"About to call mapper with {len(retailrocket_ids)} IDs")
        mapper = get_latent_mapper()
        catalog_mapping = await mapper.map_to_catalog(
            retailrocket_ids,
            confidence_threshold=settings.confidence_threshold,
            preserve_ids=True  # Returns [(UUID, retailrocket_id), ...]
        )
        logger.info(f"Mapper returned {len(catalog_mapping)} catalog mappings")
        
        if not catalog_mapping:
            logger.warning("No catalog mappings found, returning empty recommendations")
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
        filtered_products_with_scores = [
            (pid, score)
            for pid, score in product_scores
            if pid in await apply_all_rules([pid], product_metadata)
        ]
        
        # Step 7: Top-K Selection
        final_products_with_scores = filtered_products_with_scores[:k]
        
        # Step 8: Apply Session Re-Ranking (if Redis enabled)
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
            except Exception as e:
                logger.warning(f"Session re-ranking failed, using original ranking: {e}")
        
        # Build response with real LightGBM scores and product metadata
        recommendations = [
            RecommendedProduct(
                product_id=pid,
                score=score,  # Use actual LightGBM scores
                rank=rank + 1,
                name=product_metadata.get(pid, {}).get('name'),
                price=product_metadata.get(pid, {}).get('price'),
                category_name=product_metadata.get(pid, {}).get('category_name'),
                category_slug=product_metadata.get(pid, {}).get('category_slug'),
                image_url=product_metadata.get(pid, {}).get('image_url'),
                reason=f"Recommended via {strategy_used}" if include_metadata else None,
                confidence=0.85 if include_metadata else None
            )
            for rank, (pid, score) in enumerate(final_products_with_scores)
        ]
        
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
            total_returned=len(recommendations)
        )
    
    except Exception as e:
        logger.error(f"Recommendation pipeline failed: {e}", exc_info=True)
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
        
        # Try to get product metadata first to extract category
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    f"{settings.catalog_service_url}/api/v1/catalog/products/{product_id}"
                )
                if response.status_code == 200:
                    product_data = response.json()
                    category_id = product_data.get('category', {}).get('id') if isinstance(product_data.get('category'), dict) else None
                    
                    if category_id:
                        logger.info(f"Product {product_id} belongs to category {category_id}, using category-based recommendations")
                        # Get products from same category as fallback
                        category_response = await client.get(
                            f"{settings.catalog_service_url}/api/v1/catalog/products",
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
                                # Return as if they came from similarity model
                                # We'll bypass the latent mapping since we already have UUIDs
                                return ("category_similarity", similar_uuids, True)  # True = already UUIDs
        except Exception as e:
            logger.warning(f"Failed to fetch category for product {product_id}: {e}")
        
        # Original similarity model attempt
        try:
            retailrocket_id = int(product_id) if isinstance(product_id, (int, str)) and str(product_id).isdigit() else None
            
            if retailrocket_id:
                similarity_model = get_similarity_model()
                if not similarity_model.is_available():
                    try:
                        similarity_model.load()
                    except Exception as e:
                        logger.warning(f"Failed to load similarity model: {e}")
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
        except Exception as e:
            logger.warning(f"Similarity lookup failed: {e}")
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
                logger.warning(f"Failed to load SVD model: {e}")
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
        
        return HealthResponse(
            status="healthy",
            models_loaded=models_loaded,
            database_connected=db_connected
        )
    
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return HealthResponse(
            status="unhealthy",
            models_loaded={},
            database_connected=False
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
        
        if not reranker.enabled:
            return SessionTrackResponse(
                success=False,
                message="Session tracking disabled (Redis not available)"
            )
        
        if request.event_type == "category_view":
            if not request.category_slug:
                raise HTTPException(status_code=400, detail="category_slug required for category_view")
            
            await reranker.track_category_view(request.user_id, request.category_slug)
            return SessionTrackResponse(
                success=True,
                message=f"Tracked category view: {request.category_slug}"
            )
        
        elif request.event_type == "product_view":
            if not request.product_id:
                raise HTTPException(status_code=400, detail="product_id required for product_view")
            
            await reranker.track_product_view(request.user_id, request.product_id)
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
        logger.error(f"Session tracking failed: {e}")
        return SessionTrackResponse(
            success=False,
            message=f"Tracking failed: {str(e)}"
        )
