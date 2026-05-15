"""
FastAPI application entry point for Product Catalog Service.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from sqlalchemy import text

from app.core.config import settings
from app.db.session import Base, SessionLocal, engine
import app.db.models  # noqa: F401 - ensure SQLAlchemy models are registered on Base.metadata
from app.api.routes import products, categories, sellers, health, events


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup/shutdown lifecycle events.
    Tests database connection on startup.
    """
    # Startup: Ensure database schema exists for first deployment
    print("Schema initialization starting for catalog service...")
    try:
        Base.metadata.create_all(bind=engine)
        print("✓ Schema initialization succeeded")
    except Exception as e:
        print(f"✗ Schema initialization failed: {e}")
        raise

    # Startup: Test database connection
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        print("✓ Database connection established")
    except Exception as e:
        print(f"✗ Database connection failed: {e}")
        raise
    finally:
        db.close()
    
    yield  # Application runs
    
    # Shutdown: Cleanup if needed
    print("Shutting down catalog service...")


# Create FastAPI application
app = FastAPI(
    title="Product Catalog Service",
    description="API for querying products, categories, sellers, and event ingestion",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware (allow all origins for development)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for production
    allow_credentials=True,
    allow_methods=["GET", "POST", "HEAD", "OPTIONS"],  # Read + event ingestion
    allow_headers=["*"],
)

# Include routers with API prefix
app.include_router(health.router, prefix=settings.API_V1_PREFIX)
app.include_router(products.router, prefix=settings.API_V1_PREFIX)
app.include_router(categories.router, prefix=settings.API_V1_PREFIX)
app.include_router(sellers.router, prefix=settings.API_V1_PREFIX)

# Event ingestion (no API prefix, matches frontend contract: POST /events)
app.include_router(events.router)


@app.get("/")
def root():
    """Root endpoint redirect to docs."""
    return {
        "service": "Product Catalog Service",
        "version": "1.0.0",
        "docs": "/docs",
        "health": f"{settings.API_V1_PREFIX}/health"
    }
