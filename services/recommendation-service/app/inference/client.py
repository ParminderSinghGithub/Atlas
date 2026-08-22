"""
Async HTTP Client for External ML Inference.
"""
from typing import Optional, List, Union, Dict, Any
import time
import httpx
from pydantic import ValidationError

from app.core.config import settings
from app.core.logging import get_logger, log_fallback
from app.inference.schemas import InferenceRequest, InferenceResponse

logger = get_logger(__name__)


class MLInferenceClient:
    """
    Client for interacting with the external ML inference service (e.g. Hugging Face Space).
    
    Guarantees:
    - Non-blocking async execution
    - Strict timeout enforcement to protect latency SLA
    - Comprehensive exception handling (swallows network/protocol errors and returns None)
    - Zero interference with local fallback paths
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        enabled: Optional[bool] = None,
    ):
        self.base_url = (base_url or settings.ml_inference_url or "").strip().rstrip("/")
        self.timeout = float(timeout if timeout is not None else settings.ml_inference_timeout)
        self.enabled = bool(enabled if enabled is not None else settings.ml_inference_enabled)

    def is_configured(self) -> bool:
        """Check if client is enabled and has a valid base URL."""
        return self.enabled and bool(self.base_url)

    async def infer(
        self,
        user_id: Optional[str] = None,
        item_id: Optional[Union[int, str]] = None,
        candidate_ids: Optional[List[int]] = None,
        k: int = 100,
        model_version: Optional[str] = None,
        strategy: Optional[str] = None,
    ) -> Optional[InferenceResponse]:
        """
        Execute an inference request against the external ML service.

        Args:
            user_id: App UUID or RetailRocket user ID
            item_id: RetailRocket item ID for similarity queries
            candidate_ids: Optional list of candidate item IDs to re-rank
            k: Number of candidates/recommendations requested
            model_version: Optional model version tag
            strategy: Optional explicit strategy override ('svd', 'item_similarity', 'popularity', 'auto')

        Returns:
            InferenceResponse on success, or None on failure/timeout/disabled.
        """
        if not self.is_configured():
            logger.debug("External ML inference client is disabled or not configured")
            return None

        # Build and validate request payload
        try:
            req = InferenceRequest(
                user_id=str(user_id) if user_id is not None else None,
                item_id=item_id,
                candidate_ids=candidate_ids,
                k=k,
                model_version=model_version or getattr(settings, 'model_version', None),
                strategy=strategy,
            )
            payload = req.dict(exclude_none=True)
        except ValidationError as val_err:
            logger.warning("External ML inference request validation failed: %s", val_err)
            return None

        endpoint = f"{self.base_url}/infer"
        start_time = time.time()

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                logger.debug(
                    "Sending external ML inference request to %s | user_id=%s | item_id=%s | k=%d",
                    endpoint,
                    user_id,
                    item_id,
                    k,
                )
                response = await client.post(endpoint, json=payload)
                elapsed_ms = (time.time() - start_time) * 1000

                if response.status_code != 200:
                    logger.warning(
                        "External ML inference returned non-200 status: %d | elapsed=%.2fms | body=%s",
                        response.status_code,
                        elapsed_ms,
                        response.text[:200],
                    )
                    log_fallback(logger, f"http_status_{response.status_code}", "local_pipeline")
                    return None

                data = response.json()
                parsed = InferenceResponse(**data)
                logger.info(
                    "External ML inference completed successfully | strategy=%s | items=%d | elapsed=%.2fms",
                    parsed.strategy_used,
                    len(parsed.items),
                    elapsed_ms,
                )
                return parsed

        except httpx.TimeoutException as exc:
            elapsed_ms = (time.time() - start_time) * 1000
            logger.warning(
                "External ML inference timed out after %.2fms (limit=%.2fs): %s",
                elapsed_ms,
                self.timeout,
                exc,
            )
            log_fallback(logger, "external_ml_timeout", "local_pipeline")
            return None

        except httpx.ConnectError as exc:
            logger.warning("External ML inference connection failed to %s: %s", endpoint, exc)
            log_fallback(logger, "external_ml_connect_error", "local_pipeline")
            return None

        except (httpx.HTTPError, ValueError, ValidationError) as exc:
            logger.warning("External ML inference communication/parsing error: %s", exc)
            log_fallback(logger, "external_ml_protocol_error", "local_pipeline")
            return None

        except Exception as exc:
            logger.exception("Unexpected error in external ML inference client: %s", exc)
            log_fallback(logger, "external_ml_unexpected_error", "local_pipeline")
            return None

    async def health_check(self) -> bool:
        """
        Check health of external ML inference service.
        
        Returns:
            True if healthy (200 OK), False otherwise.
        """
        if not self.is_configured():
            return False

        endpoint = f"{self.base_url}/health"
        try:
            async with httpx.AsyncClient(timeout=min(self.timeout, 1.5)) as client:
                response = await client.get(endpoint)
                return response.status_code == 200
        except Exception as exc:
            logger.debug("External ML health check failed (%s): %s", endpoint, exc)
            return False


# Singleton client instance
_inference_client_instance: Optional[MLInferenceClient] = None


def get_inference_client() -> MLInferenceClient:
    """Get or create global MLInferenceClient singleton."""
    global _inference_client_instance
    if _inference_client_instance is None:
        _inference_client_instance = MLInferenceClient()
    return _inference_client_instance


def reset_inference_client() -> None:
    """Reset singleton instance (useful for testing)."""
    global _inference_client_instance
    _inference_client_instance = None
