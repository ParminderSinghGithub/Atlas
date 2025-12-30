"""
Database session management with SQLAlchemy 2.0.
Provides engine and session factory for the application.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session, DeclarativeBase
from typing import Generator

from app.core.config import settings


# SQLAlchemy 2.0 declarative base
class Base(DeclarativeBase):
    """Base class for all database models."""
    pass


# Create engine with connection pooling
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,  # Verify connections before using
    echo=False,  # Set to True for SQL query logging
)

# Session factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)


def get_db() -> Generator[Session, None, None]:
    """
    Dependency for FastAPI routes.
    Yields a database session and ensures cleanup.
    
    Usage in routes:
        @router.get("/items")
        def get_items(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
