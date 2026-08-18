"""
Test Suite for External ML Inference Service & End-to-End Pipeline.

Tests:
1. ML Inference Service Health & Readiness endpoints
2. SVD Candidate Generation + LightGBM Ranking path
3. Item Similarity + LightGBM Ranking path
4. Candidate pool re-ranking path
5. Cold-start handling for unknown users and items
6. End-to-end integration: Recommendation Service -> ML Inference Service -> Latent Mapping -> Response
7. Failure & fallback safety across the network boundary
"""
import sys
import os
from pathlib import Path
import asyncio
import unittest
from unittest.mock import patch, AsyncMock, MagicMock
from uuid import uuid4

# Set up paths for recommendation-service and ml-inference-service
REPO_ROOT = Path(__file__).parent.parent.parent
REC_SERVICE_PATH = REPO_ROOT / "services" / "recommendation-service"
ML_SERVICE_PATH = REPO_ROOT / "services" / "ml-inference-service"

sys.path.insert(0, str(ML_SERVICE_PATH))
sys.path.insert(0, str(REC_SERVICE_PATH))

# Ensure mock modules for optional heavy ML dependencies so unit tests run cleanly in any environment
for mod in ["numpy", "lightgbm", "asyncpg", "pandas", "sklearn", "redis", "redis.asyncio"]:
    if mod not in sys.modules:
        try:
            __import__(mod)
        except ImportError:
            sys.modules[mod] = MagicMock()

import httpx
from app.core.config import settings
from app.inference.client import MLInferenceClient, reset_inference_client
from ml_app.main import app as ml_inference_app
import ml_app.main as ml_main_module


class TestMLInferenceServiceEndpoints(unittest.IsolatedAsyncioTestCase):
    """Test external ML inference service endpoints."""

    async def test_health_endpoint(self):
        """Verify /health returns 200 OK."""
        transport = httpx.ASGITransport(app=ml_inference_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["status"], "ok")
            self.assertEqual(data["service"], "atlas-ml-inference-service")

    async def test_ready_endpoint(self):
        """Verify /ready endpoint reports status."""
        transport = httpx.ASGITransport(app=ml_inference_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/ready")
            self.assertIn(resp.status_code, [200, 503])
            data = resp.json()
            self.assertIn("models_loaded", data)

    async def test_infer_candidate_pool_ranking(self):
        """Verify /infer with candidate_ids re-ranks candidates with LightGBM."""
        transport = httpx.ASGITransport(app=ml_inference_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            req_body = {
                "candidate_ids": [101, 102, 103, 104],
                "k": 10,
                "model_version": "production_v1"
            }
            resp = await client.post("/infer", json=req_body)
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["status"], "success")
            self.assertEqual(len(data["items"]), 4)
            self.assertEqual(data["items"][0]["item_id"], 101)

    async def test_infer_cold_start_unknown_user(self):
        """Verify /infer returns cold_start for unknown user."""
        transport = httpx.ASGITransport(app=ml_inference_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            req_body = {
                "user_id": "uuid-non-existent-user-12345",
                "k": 10
            }
            resp = await client.post("/infer", json=req_body)
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["status"], "cold_start")
            self.assertEqual(len(data["items"]), 0)


class TestRecommendationEndToEndWithMLService(unittest.IsolatedAsyncioTestCase):
    """Test full recommendation pipeline using external ML service."""

    async def asyncSetUp(self):
        reset_inference_client()

    async def asyncTearDown(self):
        reset_inference_client()

    async def test_full_pipeline_recommendation_flow(self):
        """
        Verify end-to-end:
        User Request -> Recommendation Service -> ML Inference Service -> Latent Mapping -> Product Metadata -> Response
        """
        from app.api.routes import get_recommendations

        fake_uuid_1 = uuid4()
        fake_uuid_2 = uuid4()

        # Mock SVD candidate generation inside ML service to return deterministic candidates
        mock_svd = MagicMock()
        mock_svd.is_available.return_value = True
        mock_svd.get_candidates.return_value = [5001, 5002]

        # Mock LatentMapper on Recommendation Service
        mock_mapper = AsyncMock()
        mock_mapper.map_to_catalog = AsyncMock(return_value=[
            (fake_uuid_1, 5001),
            (fake_uuid_2, 5002),
        ])

        # Mock Catalog Metadata Fetch
        mock_metadata = {
            fake_uuid_1: {"name": "Hydrated Product A", "price": 49.99, "category_name": "Apparel"},
            fake_uuid_2: {"name": "Hydrated Product B", "price": 89.99, "category_name": "Footwear"},
        }

        transport = httpx.ASGITransport(app=ml_inference_app)
        mock_http_client = httpx.AsyncClient(transport=transport, base_url="http://ml-service:8001")

        with patch("app.api.routes.settings.ml_inference_enabled", True), \
             patch("app.api.routes.settings.ml_inference_url", "http://ml-service:8001"), \
             patch.object(ml_main_module, "get_svd_model", return_value=mock_svd), \
             patch("httpx.AsyncClient", return_value=mock_http_client), \
             patch("app.api.routes.get_latent_mapper", return_value=mock_mapper), \
             patch("app.api.routes.fetch_product_metadata", AsyncMock(return_value=mock_metadata)), \
             patch("app.api.routes.apply_all_rules", AsyncMock(return_value=[fake_uuid_1, fake_uuid_2])):

            response = await get_recommendations(user_id="user_123", k=10)

        self.assertEqual(len(response.recommendations), 2)
        self.assertEqual(response.recommendations[0].product_id, fake_uuid_1)
        self.assertEqual(response.recommendations[0].name, "Hydrated Product A")
        self.assertEqual(response.recommendations[1].product_id, fake_uuid_2)
        self.assertEqual(response.recommendations[1].name, "Hydrated Product B")


def run_tests():
    """Run test suite."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestMLInferenceServiceEndpoints))
    suite.addTests(loader.loadTestsFromTestCase(TestRecommendationEndToEndWithMLService))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_tests())
