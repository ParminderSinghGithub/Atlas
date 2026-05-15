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
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import os

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


def get_runtime_port() -> int:
    """Resolve the listening port with Railway PORT precedence."""
    return int(os.getenv("PORT") or os.getenv("SERVICE_PORT") or settings.service_port)


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
    logger.info("Catalog metadata service URL: %s", settings.catalog_service_url.rstrip("/"))
    logger.info("="*70)
    logger.info("ML MODEL INITIALIZATION")
    logger.info("="*70)
    
    try:
        # 1. Load LightGBM Ranker
        logger.info("[1/5] Loading LightGBM Ranker...")
        if settings.disable_feature_tables:
            logger.warning("  SKIP LightGBM | Ranking disabled because feature tables are unavailable.")
        else:
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
            if svd.is_available():
                logger.info(f"  PASS SVD | users={len(svd.user_mapping)} | items={len(svd.item_mapping)}")
            else:
                logger.warning("  SKIP SVD | SVD model not found — continuing without SVD recommender.")
        except Exception as e:
            logger.error(f"  FAIL SVD: {e}")
            if settings.enable_svd:
                raise
        
        # 3. Load Item-Item Similarity
        logger.info("[3/5] Loading Item-Item Similarity...")
        similarity = get_similarity_model()
        try:
            if settings.disable_similarity_model:
                logger.warning("  SKIP Similarity | Similarity recommender disabled for deployment mode.")
            else:
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
        if settings.disable_feature_tables:
            logger.warning("  SKIP Features | Feature tables disabled for lightweight deployment mode.")
            logger.warning("  SKIP Ranking | LightGBM ranking disabled because feature tables are unavailable.")
        else:
            feature_loader = get_feature_loader()
            logger.info("DEBUG: Feature loader returned successfully")
            try:
                user_count = len(feature_loader.user_features) if feature_loader.user_features is not None else 0
                logger.info(f"DEBUG: User count = {user_count}")
                item_count = len(feature_loader.item_features) if feature_loader.item_features is not None else 0
                logger.info(f"DEBUG: Item count = {item_count}")
                logger.info(f"  PASS Features | users={user_count} | items={item_count}")
            except Exception as e:
                logger.error(f"ERROR accessing features: {e}", exc_info=True)
                raise
        
        logger.info("="*70)
        logger.info(f"Loaded models from version: {settings.model_version}")
        logger.info("="*70)
        
        # Database connection is LAZY - will connect on first request
        # (Skip connection during startup to avoid blocking pod initialization)
        logger.info("="*70)
        logger.info("DATABASE CONNECTION")
        logger.info("="*70)
        logger.info("  SKIP Database connection deferred to first request (lazy initialization)")
        
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
        
        # Warm-up: Execute a test recommendation to load all lazy components
        # Warm-up is DISABLED to avoid blocking startup with database connection
        # Database will connect lazily on first actual request
        logger.info("="*70)
        logger.info("MODEL WARM-UP")
        logger.info("="*70)
        logger.info("  SKIP Warm-up disabled (will initialize on first request)")
        
        logger.info("="*70)
        logger.info("RECOMMENDATION SERVICE READY")
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


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Log uncaught exceptions with request context and traceback."""
    logger.exception(
        "Unhandled exception | method=%s | path=%s | query_params=%s",
        request.method,
        request.url.path,
        dict(request.query_params),
    )
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


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
        port=get_runtime_port(),
        reload=False  # Disable in production
    )
