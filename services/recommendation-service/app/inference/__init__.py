"""
External ML Inference Package for Atlas Recommendation Service.
"""
from app.inference.schemas import InferenceRequest, InferenceResponse, InferredItem
from app.inference.client import MLInferenceClient, get_inference_client, reset_inference_client
from app.inference.mock_server import mock_ml_app

__all__ = [
    "InferenceRequest",
    "InferenceResponse",
    "InferredItem",
    "MLInferenceClient",
    "get_inference_client",
    "reset_inference_client",
    "mock_ml_app",
]
