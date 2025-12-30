"""
Health check API route.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime

from app.db.session import get_db
from app.api.schemas import HealthCheckResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthCheckResponse)
def health_check(db: Session = Depends(get_db)):
    """
    Health check endpoint for catalog service.
    
    Checks:
    - Service is running (returns 200)
    - Database connection is active
    
    Returns:
    - status: "healthy" or "unhealthy"
    - database: "connected" or "disconnected"
    - timestamp: Current UTC timestamp
    """
    # Test database connection
    db_status = "connected"
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_status = "disconnected"
    
    # Overall status
    status = "healthy" if db_status == "connected" else "unhealthy"
    
    return HealthCheckResponse(
        status=status,
        database=db_status,
        timestamp=datetime.utcnow()
    )
