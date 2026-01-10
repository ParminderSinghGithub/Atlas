"""
Event Ingestion Routes

Handles user behavior event tracking (view, click, add_to_cart, purchase).
Events are written directly to PostgreSQL for analytics and future ML retraining.
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, Literal
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import text
import uuid
import json

from app.db.session import get_db


router = APIRouter(tags=["events"])


class Event(BaseModel):
    """Event payload model matching frontend contract."""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: Literal["view", "click", "add_to_cart", "purchase"]
    user_id: Optional[str] = None
    session_id: str
    product_id: Optional[str] = None
    ts: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    properties: Dict[str, Any] = Field(default_factory=dict)


def ensure_events_table(db: Session):
    """
    Create events table if not exists (idempotent).
    
    Schema Authority: docs/DATA_CARD.md (Events Table Schema section)
    
    Note: This is temporary schema management. For production scale,
    migrate to Alembic migrations when events table becomes critical.
    See docs/DATA_CARD.md for recommended indexes.
    """
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS events (
            event_id VARCHAR(255) PRIMARY KEY,
            event_type VARCHAR(50),
            user_id VARCHAR(255),
            session_id VARCHAR(255),
            product_id VARCHAR(255),
            properties JSONB,
            ts TIMESTAMPTZ
        )
    """))
    db.commit()


@router.post("/events", status_code=201)
async def ingest_event(event: Event, db: Session = Depends(get_db)):
    """
    Ingest user behavior event.
    
    Writes directly to PostgreSQL events table for:
    - Analytics queries
    - Future ML retraining (when production scale justifies)
    
    Returns:
        {"status": "ok", "event_id": "..."}
    
    Note: This endpoint replaced Kafka-based async ingestion.
    At demonstration scale (<10K MAU), synchronous writes are sufficient.
    """
    try:
        # Ensure table exists (idempotent check)
        ensure_events_table(db)
        
        # Insert event with conflict handling (idempotent)
        db.execute(
            text("""
                INSERT INTO events (event_id, event_type, user_id, session_id, product_id, properties, ts)
                VALUES (:event_id, :event_type, :user_id, :session_id, :product_id, :properties, :ts)
                ON CONFLICT (event_id) DO NOTHING
            """),
            {
                "event_id": event.event_id,
                "event_type": event.event_type,
                "user_id": event.user_id,
                "session_id": event.session_id,
                "product_id": event.product_id,
                "properties": json.dumps(event.properties),
                "ts": event.ts,
            }
        )
        db.commit()
        
        return {"status": "ok", "event_id": event.event_id}
    
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to store event: {str(e)}"
        )


@router.get("/events/health")
async def events_health_check():
    """Health check for event ingestion endpoint."""
    return {"status": "healthy", "service": "event-ingestion"}
