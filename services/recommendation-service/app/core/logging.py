"""
Structured logging for Recommendation Service.

Why structured logging:
- Machine-readable logs for production monitoring
- Contextual information (request_id, user_id, latency)
- Easy integration with ELK, Datadog, etc.
"""
import logging
import sys
import json
import hashlib
from typing import Any, Dict, List, Optional
from datetime import datetime
from uuid import UUID
from app.core.config import settings


# Configure logging format
def setup_logging():
    """Configure structured logging with JSON output."""
    
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    
    # Create formatter
    formatter = logging.Formatter(
        fmt='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    
    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.addHandler(console_handler)
    
    # Silence noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    
    return root_logger


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with the given name."""
    return logging.getLogger(name)


def log_request(logger: logging.Logger, endpoint: str, params: Dict[str, Any], latency_ms: float):
    """
    Log API request with context.
    
    Why: Production debugging requires structured logs with latency metrics.
    """
    logger.info(
        f"Request to {endpoint} | params={params} | latency={latency_ms:.2f}ms"
    )


def log_fallback(logger: logging.Logger, reason: str, fallback_strategy: str):
    """
    Log when fallback logic is triggered.
    
    Why: Critical for monitoring model health and cold start rates.
    """
    logger.warning(
        f"Fallback triggered | reason={reason} | strategy={fallback_strategy}"
    )


def log_cache_miss(logger: logging.Logger, cache_key: str):
    """
    Log cache miss.
    
    Why: Monitor cache hit rates for optimization opportunities.
    """
    logger.debug(f"Cache miss | key={cache_key}")


def log_cache_error(logger: logging.Logger, error: Exception):
    """
    Log cache errors without breaking request.
    
    Why: Redis failures should not crash the service.
    """
    logger.warning(f"Cache error (continuing without cache) | error={str(error)}")


def hash_user_id(user_id: str) -> str:
    """
    Hash user ID for privacy-preserving logging.
    
    Why: GDPR/privacy compliance - don't log raw user identifiers.
    """
    return hashlib.sha256(str(user_id).encode()).hexdigest()[:16]


def log_recommendation(
    logger: logging.Logger,
    user_id: Optional[str],
    product_id: Optional[UUID],
    strategy_used: str,
    model_version: str,
    recommended_items: List[UUID],
    latency_ms: float,
    candidate_sources: Optional[Dict[str, int]] = None
):
    """
    Log recommendation request in structured JSON format for monitoring.
    
    Purpose: Enable offline metrics aggregation and drift detection.
    
    Logged fields:
    - timestamp: ISO format for time-series analysis
    - user_id_hash: Privacy-preserving user identifier
    - product_id: Context item for similarity-based recs
    - strategy: Candidate generation strategy used
    - model_version: Model artifact version for A/B testing
    - recommended_items: Top-N product UUIDs (coverage analysis)
    - latency_ms: Serving latency for performance monitoring
    - candidate_sources: Breakdown of candidate generation (e.g., {"svd": 80, "popularity": 20})
    
    Why JSON:
    - Machine-readable for log aggregation tools
    - Structured parsing with jq, Python, etc.
    - No heavy observability stack required
    """
    log_entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "event_type": "recommendation",
        "user_id_hash": hash_user_id(user_id) if user_id else None,
        "product_id": str(product_id) if product_id else None,
        "strategy": strategy_used,
        "model_version": model_version,
        "recommended_items": [str(item_id) for item_id in recommended_items],
        "num_recommendations": len(recommended_items),
        "latency_ms": round(latency_ms, 2),
        "candidate_sources": candidate_sources or {}
    }
    
    # Log as JSON string for structured parsing
    logger.info(f"RECOMMENDATION_EVENT: {json.dumps(log_entry)}")
