"""
Structured logging for Recommendation Service.

Why structured logging:
- Machine-readable logs for production monitoring
- Contextual information (request_id, user_id, latency)
- Easy integration with ELK, Datadog, etc.
"""
import logging
import sys
from typing import Any, Dict
from datetime import datetime
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
