"""
FastAPI application entry point for Product Catalog Service.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from sqlalchemy import text

from app.core.config import settings
from app.db.session import SessionLocal
from app.api.routes import products, categories, sellers, health


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup/shutdown lifecycle events.
    Tests database connection on startup.
    """
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
    description="Read-only API for querying products, categories, and sellers",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware (allow all origins for development)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for production
    allow_credentials=True,
    allow_methods=["GET", "HEAD", "OPTIONS"],  # Read-only API
    allow_headers=["*"],
)

# Include routers with API prefix
app.include_router(health.router, prefix=settings.API_V1_PREFIX)
app.include_router(products.router, prefix=settings.API_V1_PREFIX)
app.include_router(categories.router, prefix=settings.API_V1_PREFIX)
app.include_router(sellers.router, prefix=settings.API_V1_PREFIX)


@app.get("/")
def root():
    """Root endpoint redirect to docs."""
    return {
        "service": "Product Catalog Service",
        "version": "1.0.0",
        "docs": "/docs",
        "health": f"{settings.API_V1_PREFIX}/health"
    }
