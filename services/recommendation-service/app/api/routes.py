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

from app.api.schemas import (
    RecommendationRequest,
    RecommendationResponse,
    RecommendedProduct,
    HealthResponse
)
from app.models.svd import get_svd_model
from app.models.popularity import get_popularity_model
from app.models.lightgbm_ranker import get_ranker
from app.models.similarity import get_similarity_model
from app.features.loader import get_feature_loader
from app.mapping.latent_mapper import get_latent_mapper
from app.decisioning.rules import apply_all_rules
from app.core.config import settings
from app.core.logging import get_logger, log_request, log_fallback

logger = get_logger(__name__)
router = APIRouter()


async def fetch_product_metadata(product_ids: List[UUID]) -> Dict[UUID, Dict[str, Any]]:
    """
    Fetch product metadata from catalog service.
    
    Why needed:
    - Stock filtering (stock_quantity)
    - Diversity constraint (category_id)
    - Inactive filtering (is_deleted)
    
    Production: This would call catalog-service API
    For now: Return mock data (TODO: implement catalog client)
    """
    # TODO: Replace with actual HTTP call to catalog-service
    # async with httpx.AsyncClient() as client:
    #     response = await client.post(
    #         "http://catalog-service:5004/api/v1/catalog/products/batch",
    #         json={"product_ids": [str(pid) for pid in product_ids]}
    #     )
    #     return response.json()
    
    # Mock metadata (all products in stock, not deleted, random categories)
    return {
        pid: {
            'stock_quantity': 10,
            'is_deleted': False,
            'category_id': hash(pid) % 10  # Mock category distribution
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
        strategy_used, retailrocket_ids = await generate_candidates(
            user_id=user_id,
            product_id=product_id,
            k=settings.candidate_pool_size
        )
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
                logger.error(f"LightGBM ranking failed, using candidate order: {e}")
                log_fallback(logger, "lightgbm_failure", "candidate_order")
                # Fallback: use candidate order with descending scores
                ranked_items_with_scores = [
                    (item_id, 1.0 - (i * 0.01))
                    for i, item_id in enumerate(retailrocket_ids)
                ]
                strategy_used = f"{strategy_used}_no_ranking"
        else:
            logger.info("LightGBM disabled or unavailable, using candidate order")
            # Fallback: use candidate order with descending scores
            ranked_items_with_scores = [
                (item_id, 1.0 - (i * 0.01))
                for i, item_id in enumerate(retailrocket_ids)
            ]
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
        
        # Build response with real LightGBM scores
        recommendations = [
            RecommendedProduct(
                product_id=pid,
                score=score,  # Use actual LightGBM scores
                rank=rank + 1,
                reason=f"Recommended via {strategy_used}" if include_metadata else None,
                confidence=0.85 if include_metadata else None  # TODO: Use actual mapping confidence
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
        
        # Try to convert product_id to RetailRocket item ID via reverse mapping
        # For now, assume product_id is already a RetailRocket ID if it's an integer
        try:
            # TODO: Implement reverse catalog→latent lookup in mapper
            # For now, treat string product_ids as RetailRocket IDs
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
                        return ("popularity", popularity_model.get_top_k(k))
                
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
                return ("popularity", popularity_model.get_top_k(k))
        
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
    return ("popularity", popularity_model.get_top_k(k))


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
