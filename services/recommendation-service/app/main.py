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
from app.features.loader import get_feature_loader
from app.mapping.latent_mapper import get_latent_mapper

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
    
    try:
        # Load models (lazy loading - will load on first use)
        logger.info("Initializing models...")
        ranker = get_ranker()
        svd = get_svd_model()
        popularity = get_popularity_model()
        
        # Load feature tables
        logger.info("Loading feature tables...")
        feature_loader = get_feature_loader()
        
        # Connect to database
        logger.info("Connecting to database...")
        mapper = get_latent_mapper()
        await mapper.connect()
        
        logger.info(f"{settings.service_name} started successfully on port {settings.service_port}")
    
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
