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

from app.api.schemas import (
    RecommendationRequest,
    RecommendationResponse,
    RecommendedProduct,
    HealthResponse
)
from app.models.svd import get_svd_model
from app.models.popularity import get_popularity_model
from app.models.lightgbm_ranker import get_ranker
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
        
        # Step 3: Ranking with LightGBM
        ranker = get_ranker()
        if ranker.is_available() and settings.enable_lightgbm_ranking:
            try:
                scores = ranker.predict(features_df)
                # Sort by score descending
                sorted_indices = scores.argsort()[::-1]
                retailrocket_ids = [retailrocket_ids[i] for i in sorted_indices]
                logger.debug(f"LightGBM ranking complete | mean_score={scores.mean():.4f}")
            except Exception as e:
                logger.error(f"LightGBM ranking failed, using candidate order: {e}")
                log_fallback(logger, "lightgbm_failure", "candidate_order")
        else:
            logger.debug("LightGBM disabled, using candidate order")
        
        # Step 4: Latent → Catalog Mapping
        logger.info(f"About to call mapper with {len(retailrocket_ids)} IDs")
        mapper = get_latent_mapper()
        catalog_product_ids = await mapper.map_to_catalog(
            retailrocket_ids,
            confidence_threshold=settings.confidence_threshold
        )
        logger.info(f"Mapper returned {len(catalog_product_ids)} catalog IDs")
        
        if not catalog_product_ids:
            logger.warning("No catalog mappings found, returning empty recommendations")
            return RecommendationResponse(
                recommendations=[],
                strategy_used=strategy_used,
                total_candidates=len(retailrocket_ids),
                total_returned=0
            )
        
        logger.debug(f"Mapped to {len(catalog_product_ids)} catalog products")
        
        # Step 5: Fetch Product Metadata
        product_metadata = await fetch_product_metadata(catalog_product_ids)
        
        # Step 6: Apply Decisioning Rules
        filtered_products = await apply_all_rules(catalog_product_ids, product_metadata)
        
        # Step 7: Top-K Selection
        final_products = filtered_products[:k]
        
        # Build response
        recommendations = [
            RecommendedProduct(
                product_id=pid,
                score=1.0 - (rank * 0.01),  # Mock scores (TODO: use actual LightGBM scores)
                rank=rank + 1,
                reason=f"Recommended via {strategy_used}" if include_metadata else None,
                confidence=0.85 if include_metadata else None  # Mock confidence
            )
            for rank, pid in enumerate(final_products)
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
    Generate candidate items.
    
    Strategy priority:
    1. Product-based (if product_id provided)
    2. User-based SVD (if user_id known)
    3. Popularity baseline (cold start)
    
    Returns:
        (strategy_name, retailrocket_item_ids)
    """
    # Strategy 1: Product-based similarity
    if product_id is not None:
        # TODO: Implement item-item similarity
        # For now, fallback to popularity
        logger.debug(f"Product-based recommendations requested for {product_id}")
        log_fallback(logger, "item_similarity_not_implemented", "popularity")
        popularity_model = get_popularity_model()
        return ("popularity", popularity_model.get_top_k(k))
    
    # Strategy 2: User-based SVD
    if user_id is not None and settings.enable_svd:
        svd_model = get_svd_model()
        if svd_model.is_available():
            candidates = svd_model.get_candidates(user_id, k)
            if candidates:
                logger.debug(f"SVD candidates generated for user {user_id}")
                return ("svd", candidates)
            else:
                logger.debug(f"User {user_id} not in SVD model (cold start)")
                log_fallback(logger, "unknown_user", "popularity")
    
    # Strategy 3: Popularity baseline (cold start)
    logger.debug("Using popularity baseline")
    popularity_model = get_popularity_model()
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
        popularity = get_popularity_model()
        
        models_loaded = {
            "lightgbm": ranker.is_available(),
            "svd": svd.is_available(),
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
