"""
Recommendation Service - Phase 2.3

FastAPI application for serving ML-based recommendations.

Service responsibilities:
- Load trained ML models (LightGBM, SVD, popularity)
- Serve recommendations via REST API
- Bridge offline ML (RetailRocket IDs) → online catalog (UUIDs)
- Apply business rules (diversity, stock filtering)
- Handle cold start gracefully
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.core.config import settings
from app.core.logging import setup_logging, get_logger
from app.api.routes import router
from app.models.lightgbm_ranker import get_ranker
from app.models.svd import get_svd_model
from app.models.popularity import get_popularity_model
from app.models.similarity import get_similarity_model
from app.features.loader import get_feature_loader
from app.mapping.latent_mapper import get_latent_mapper
from app.session.reranker import get_session_reranker

# Setup logging
setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan: startup and shutdown logic.
    
    Startup:
    - Load ML models
    - Load feature tables
    - Connect to database
    
    Shutdown:
    - Close database connections
    - Cleanup resources
    """
    # Startup
    logger.info(f"Starting {settings.service_name}...")
    logger.info("="*70)
    logger.info("ML MODEL INITIALIZATION")
    logger.info("="*70)
    
    try:
        # 1. Load LightGBM Ranker
        logger.info("[1/5] Loading LightGBM Ranker...")
        ranker = get_ranker()
        try:
            ranker.load()
            logger.info(f"  PASS LightGBM | features={len(ranker.feature_names)}")
        except Exception as e:
            logger.error(f"  FAIL LightGBM: {e}")
            if settings.enable_lightgbm_ranking:
                raise
        
        # 2. Load SVD Model
        logger.info("[2/5] Loading SVD Model...")
        svd = get_svd_model()
        try:
            svd.load()
            logger.info(f"  PASS SVD | users={len(svd.user_mapping)} | items={len(svd.item_mapping)}")
        except Exception as e:
            logger.error(f"  FAIL SVD: {e}")
            if settings.enable_svd:
                raise
        
        # 3. Load Item-Item Similarity
        logger.info("[3/5] Loading Item-Item Similarity...")
        similarity = get_similarity_model()
        try:
            similarity.load()
            logger.info(f"  PASS Similarity | items={len(similarity.similarity_dict)}")
        except Exception as e:
            logger.error(f"  FAIL Similarity: {e}")
            if settings.enable_item_similarity:
                raise
        
        # 4. Load Popularity Baseline
        logger.info("[4/5] Loading Popularity Baseline...")
        popularity = get_popularity_model()
        try:
            popularity.load()
            logger.info(f"  PASS Popularity | items={len(popularity.popularity_scores)}")
        except Exception as e:
            logger.error(f"  FAIL Popularity: {e}")
            raise
        
        # 5. Load Feature Tables
        logger.info("[5/5] Loading Feature Tables...")
        feature_loader = get_feature_loader()
        logger.info(f"  PASS Features | users={len(feature_loader.user_features) if feature_loader.user_features is not None else 0} | items={len(feature_loader.item_features) if feature_loader.item_features is not None else 0}")
        
        # Connect to database
        logger.info("="*70)
        logger.info("DATABASE CONNECTION")
        logger.info("="*70)
        mapper = get_latent_mapper()
        await mapper.connect()
        logger.info(f"  PASS Database connected")
        
        # Initialize session reranker
        logger.info("="*70)
        logger.info("SESSION TRACKING")
        logger.info("="*70)
        if settings.redis_enabled:
            reranker = await get_session_reranker(settings.redis_url)
            logger.info(f"  PASS Session tracking enabled")
        else:
            logger.info(f"  SKIP Session tracking disabled (set REDIS_ENABLED=true to enable)")
        
        logger.info("="*70)
        logger.info(f"STARTUP COMPLETE - {settings.service_name}")
        logger.info(f"Port: {settings.service_port}")
        logger.info("="*70)
    
    except Exception as e:
        logger.error(f"Failed to start service: {e}", exc_info=True)
        raise
    
    yield  # Service is running
    
    # Shutdown
    logger.info(f"Shutting down {settings.service_name}...")
    try:
        # Close database connection
        mapper = get_latent_mapper()
        await mapper.close()
        logger.info("Service shutdown complete")
    except Exception as e:
        logger.error(f"Error during shutdown: {e}", exc_info=True)


# Create FastAPI app
app = FastAPI(
    title="P1 Recommendation Service",
    description="ML-powered recommendation engine for P1 e-commerce platform",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS middleware (allow API Gateway and frontend)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",  # API Gateway
        "http://localhost:5174",  # Frontend
        "http://localhost:3000"   # Alternative frontend port
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"]
)

# Register routes
app.include_router(router, tags=["recommendations"])


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": settings.service_name,
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.service_port,
        reload=False  # Disable in production
    )
