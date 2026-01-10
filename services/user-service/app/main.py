"""
User Service - FastAPI Application

Python replacement for Node.js Express user-service.

CRITICAL: Must maintain API compatibility with:
- Frontend (React)
- API Gateway (FastAPI proxy)
- JWT tokens (Node.js jsonwebtoken library)
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import router
from app.core import Base, engine
from app.core.config import settings

# Create FastAPI application
app = FastAPI(
    title="User Service",
    description="Authentication service for Atlas e-commerce platform",
    version="2.0.0"
)

# CORS middleware (matches Node.js cors())
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins (matches Node.js)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount authentication routes under /api/auth
app.include_router(router, prefix="/api/auth")


@app.on_event("startup")
async def startup_event():
    """
    Application startup.
    
    Initialize database tables if they don't exist.
    
    Note: In production, use Alembic migrations instead of create_all().
    For development, this ensures tables exist on first run.
    """
    print(f"Starting {settings.service_name}...")
    print(f"Database: {settings.postgres_uri.split('@')[1]}")  # Hide password
    
    # Create tables (idempotent - only creates if not exist)
    Base.metadata.create_all(bind=engine)
    
    print(f"✓ Database tables synchronized")
    print(f"✓ {settings.service_name} ready on port {settings.service_port}")


@app.on_event("shutdown")
async def shutdown_event():
    """Application shutdown cleanup."""
    print(f"Shutting down {settings.service_name}...")


# Root endpoint for health check
@app.get("/")
def root():
    """Root endpoint."""
    return {"service": settings.service_name, "version": "2.0.0", "status": "ok"}
