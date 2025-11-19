from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator
from typing import Optional, Dict, Any, Literal
from datetime import datetime, timezone
import uuid
import json

from app.kafka_producer import get_producer, close_producer

app = FastAPI(title="Event Ingestion Service")


class Event(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: Literal["view", "click", "add_to_cart", "purchase"]
    user_id: Optional[str] = None
    session_id: str
    product_id: Optional[str] = None
    ts: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    properties: Dict[str, Any] = Field(default_factory=dict)


@app.on_event("startup")
async def startup_event():
    """Initialize Kafka producer on startup."""
    await get_producer()


@app.on_event("shutdown")
async def shutdown_event():
    """Close Kafka producer on shutdown."""
    await close_producer()


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.post("/events", status_code=201)
async def ingest_event(event: Event):
    """
    Ingest user event and publish to Kafka.
    
    Partition key: user_id if available, else session_id.
    Topic: user_events
    """
    try:
        producer = await get_producer()
        
        # Determine partition key
        partition_key = event.user_id if event.user_id else event.session_id
        
        # Serialize event to JSON
        event_data = event.model_dump()
        event_json = json.dumps(event_data).encode("utf-8")
        
        # Send to Kafka with durability guarantee
        await producer.send_and_wait(
            topic="user_events",
            value=event_json,
            key=partition_key.encode("utf-8")
        )
        
        return {
            "status": "ok",
            "event_id": event.event_id
        }
    
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to publish event: {str(e)}"
        )
