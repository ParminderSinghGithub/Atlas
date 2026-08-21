"""
Test Suite for External ML Inference Boundary.

Tests:
1. Schema validation (InferenceRequest, InferredItem, InferenceResponse)
2. Client behavior when disabled (default state)
3. Client successful inference against reference mock server (SVD, Similarity, Ranking)
4. Client timeout handling (fail-open, returns None)
5. Client connection error handling (unreachable host)
6. Client HTTP 500 error handling
7. Client malformed response handling
8. Client health check functionality
9. Route integration with external ML enabled
10. Route fallback behavior when external ML fails or is cold-start

Can be run with:
  pytest tests/recommendation/test_ml_inference_boundary.py
  python tests/recommendation/test_ml_inference_boundary.py
"""
import sys
import os
from pathlib import Path
import asyncio
import unittest
from unittest.mock import patch, AsyncMock, MagicMock
from uuid import uuid4

# Set up path to include recommendation-service
REC_SERVICE_PATH = Path(__file__).parent.parent.parent / "services" / "recommendation-service"
sys.path.insert(0, str(REC_SERVICE_PATH))
# Ensure mock modules for optional heavy ML dependencies so unit tests run cleanly in any environment
for mod in ["numpy", "lightgbm", "asyncpg", "pandas", "sklearn", "redis", "redis.asyncio"]:
    if mod not in sys.modules:
        try:
            __import__(mod)
        except ImportError:
            sys.modules[mod] = MagicMock()

import httpx
from pydantic import ValidationError

from app.core.config import settings, Settings
from app.inference.schemas import InferenceRequest, InferenceResponse, InferredItem
from app.inference.client import MLInferenceClient, get_inference_client, reset_inference_client
from app.inference.mock_server import mock_ml_app


class TestMLInferenceSchemas(unittest.TestCase):
    """Test Pydantic contract schemas."""

    def test_inference_request_valid(self):
        req = InferenceRequest(
            user_id="user_123",
            item_id=456,
            candidate_ids=[1, 2, 3],
            k=50,
            model_version="v1"
        )
        self.assertEqual(req.user_id, "user_123")
        self.assertEqual(req.item_id, 456)
        self.assertEqual(req.candidate_ids, [1, 2, 3])
        self.assertEqual(req.k, 50)
        self.assertEqual(req.model_version, "v1")

    def test_inference_request_defaults(self):
        req = InferenceRequest()
        self.assertIsNone(req.user_id)
        self.assertIsNone(req.item_id)
        self.assertIsNone(req.candidate_ids)
        self.assertEqual(req.k, 100)
        self.assertIsNone(req.model_version)

    def test_inference_request_k_bounds(self):
        with self.assertRaises(ValueError):
            InferenceRequest(k=0)
        with self.assertRaises(ValueError):
            InferenceRequest(k=501)

    def test_inference_response_valid(self):
        resp = InferenceResponse(
            status="success",
            items=[
                InferredItem(item_id=101, score=0.95),
                InferredItem(item_id=102, score=0.85),
            ],
            strategy_used="two_stage_svd_lgbm",
            model_version="production_v1",
            execution_time_ms=12.5
        )
        self.assertEqual(resp.status, "success")
        self.assertEqual(len(resp.items), 2)
        self.assertEqual(resp.items[0].item_id, 101)
        self.assertEqual(resp.items[0].score, 0.95)
        self.assertEqual(resp.strategy_used, "two_stage_svd_lgbm")

    def test_inference_response_cold_start(self):
        resp = InferenceResponse(
            status="cold_start",
            items=[],
            strategy_used="svd_cold_start"
        )
        self.assertEqual(resp.status, "cold_start")
        self.assertEqual(len(resp.items), 0)


class TestMLInferenceClient(unittest.IsolatedAsyncioTestCase):
    """Test MLInferenceClient network, error handling, and timeout behavior."""

    async def asyncSetUp(self):
        reset_inference_client()

    async def asyncTearDown(self):
        reset_inference_client()

    async def test_client_disabled_by_default(self):
        """Client must return None without making network calls when disabled."""
        client = MLInferenceClient(enabled=False, base_url=None)
        self.assertFalse(client.is_configured())
        result = await client.infer(user_id="123", k=10)
        self.assertIsNone(result)

    async def test_client_success_with_mock_server_user_svd(self):
        """Test user personalization inference roundtrip against reference mock server."""
        # Use ASGI transport to query mock_ml_app directly in memory
        transport = httpx.ASGITransport(app=mock_ml_app)
        client = MLInferenceClient(
            base_url="http://testserver",
            timeout=5.0,
            enabled=True
        )

        with patch("httpx.AsyncClient", return_value=httpx.AsyncClient(transport=transport, base_url="http://testserver")):
            result = await client.infer(user_id="test_user_42", k=10)

        self.assertIsNotNone(result)
        self.assertEqual(result.status, "success")
        self.assertEqual(result.strategy_used, "two_stage_svd_lgbm")
        self.assertTrue(len(result.items) > 0)
        self.assertIsInstance(result.items[0].item_id, int)
        self.assertIsInstance(result.items[0].score, float)

    async def test_client_success_with_mock_server_item_similarity(self):
        """Test item similarity inference roundtrip against reference mock server."""
        transport = httpx.ASGITransport(app=mock_ml_app)
        client = MLInferenceClient(
            base_url="http://testserver",
            timeout=5.0,
            enabled=True
        )

        with patch("httpx.AsyncClient", return_value=httpx.AsyncClient(transport=transport, base_url="http://testserver")):
            result = await client.infer(item_id=5500, k=5)

        self.assertIsNotNone(result)
        self.assertEqual(result.status, "success")
        self.assertEqual(result.strategy_used, "two_stage_item_sim_lgbm")
        self.assertTrue(len(result.items) > 0)

    async def test_client_mock_server_cold_start(self):
        """Test that cold start returns valid InferenceResponse with status='cold_start'."""
        transport = httpx.ASGITransport(app=mock_ml_app)
        client = MLInferenceClient(
            base_url="http://testserver",
            timeout=5.0,
            enabled=True
        )

        with patch("httpx.AsyncClient", return_value=httpx.AsyncClient(transport=transport, base_url="http://testserver")):
            result = await client.infer(user_id="cold_start_user", k=10)

        self.assertIsNotNone(result)
        self.assertEqual(result.status, "cold_start")
        self.assertEqual(len(result.items), 0)

    async def test_client_timeout_handling(self):
        """Test that client gracefully catches timeout, logs fallback, and returns None."""
        client = MLInferenceClient(
            base_url="http://testserver",
            timeout=0.001,
            enabled=True
        )

        # Mock AsyncClient.post to raise TimeoutException
        async def slow_post(*args, **kwargs):
            raise httpx.TimeoutException("Connection timed out")

        mock_client = AsyncMock()
        mock_client.post = slow_post
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await client.infer(user_id="123", k=10)

        self.assertIsNone(result)

    async def test_client_connection_error_handling(self):
        """Test that client catches connection failure and returns None."""
        client = MLInferenceClient(
            base_url="http://unreachable-host:9999",
            timeout=1.0,
            enabled=True
        )

        async def conn_err(*args, **kwargs):
            raise httpx.ConnectError("Failed to establish connection")

        mock_client = AsyncMock()
        mock_client.post = conn_err
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await client.infer(user_id="123", k=10)

        self.assertIsNone(result)

    async def test_client_http_500_error_handling(self):
        """Test that non-200 responses return None."""
        client = MLInferenceClient(
            base_url="http://testserver",
            timeout=2.0,
            enabled=True
        )

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await client.infer(user_id="123", k=10)

        self.assertIsNone(result)

    async def test_client_malformed_json_handling(self):
        """Test that malformed/invalid schema response returns None."""
        client = MLInferenceClient(
            base_url="http://testserver",
            timeout=2.0,
            enabled=True
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"invalid": "payload", "items": "not_a_list"})

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await client.infer(user_id="123", k=10)

        self.assertIsNone(result)

    async def test_client_health_check(self):
        """Test health check against mock server."""
        transport = httpx.ASGITransport(app=mock_ml_app)
        client = MLInferenceClient(
            base_url="http://testserver",
            timeout=2.0,
            enabled=True
        )

        with patch("httpx.AsyncClient", return_value=httpx.AsyncClient(transport=transport, base_url="http://testserver")):
            is_healthy = await client.health_check()

        self.assertTrue(is_healthy)

        # Disabled client returns False
        disabled_client = MLInferenceClient(enabled=False)
        self.assertFalse(await disabled_client.health_check())


class TestRecommendationRouteWithExternalML(unittest.IsolatedAsyncioTestCase):
    """Test recommendation route integration and fallback logic."""

    async def asyncSetUp(self):
        reset_inference_client()

    async def asyncTearDown(self):
        reset_inference_client()

    async def test_route_external_ml_success_flow(self):
        """When external ML returns valid candidates, route maps them and returns response."""
        from app.api.routes import get_recommendations

        fake_uuid_1 = uuid4()
        fake_uuid_2 = uuid4()

        # Mock external ML response
        mock_inference_response = InferenceResponse(
            status="success",
            items=[
                InferredItem(item_id=1001, score=0.95),
                InferredItem(item_id=1002, score=0.88),
            ],
            strategy_used="two_stage_svd_lgbm",
            model_version="production_v1"
        )

        mock_client = AsyncMock()
        mock_client.infer = AsyncMock(return_value=mock_inference_response)

        # Mock latent mapper
        mock_mapper = AsyncMock()
        mock_mapper.map_to_catalog = AsyncMock(return_value=[
            (fake_uuid_1, 1001),
            (fake_uuid_2, 1002),
        ])

        # Mock metadata fetch
        mock_metadata = {
            fake_uuid_1: {"name": "Product 1", "price": 29.99, "category_name": "Electronics"},
            fake_uuid_2: {"name": "Product 2", "price": 49.99, "category_name": "Home"},
        }

        with patch("app.api.routes.settings.ml_inference_enabled", True), \
             patch("app.api.routes.settings.ml_inference_url", "http://mock-ml:8001"), \
             patch("app.api.routes.get_inference_client", return_value=mock_client), \
             patch("app.api.routes.get_latent_mapper", return_value=mock_mapper), \
             patch("app.api.routes.fetch_product_metadata", AsyncMock(return_value=mock_metadata)), \
             patch("app.api.routes.apply_all_rules", AsyncMock(return_value=[fake_uuid_1, fake_uuid_2])):

            response = await get_recommendations(user_id="user_test", k=10)

        self.assertEqual(response.strategy_used, "two_stage_svd_lgbm")
        self.assertEqual(len(response.recommendations), 2)
        self.assertEqual(response.recommendations[0].product_id, fake_uuid_1)
        self.assertEqual(response.recommendations[0].score, 0.95)
        self.assertEqual(response.recommendations[1].product_id, fake_uuid_2)
        self.assertEqual(response.recommendations[1].score, 0.88)

    async def test_route_external_ml_failure_safe_fallback(self):
        """When external ML fails, route safely falls back to local candidate generation."""
        from app.api.routes import get_recommendations

        fake_uuid = uuid4()

        # Mock external client returning None (failed/timeout)
        mock_client = AsyncMock()
        mock_client.infer = AsyncMock(return_value=None)

        # Mock local candidate generation
        local_candidates = ("popularity", [(2001, 0.5)])

        mock_mapper = AsyncMock()
        mock_mapper.map_to_catalog = AsyncMock(return_value=[(fake_uuid, 2001)])

        mock_metadata = {
            fake_uuid: {"name": "Fallback Product", "price": 9.99, "category_name": "General"}
        }

        with patch("app.api.routes.settings.ml_inference_enabled", True), \
             patch("app.api.routes.settings.ml_inference_url", "http://mock-ml:8001"), \
             patch("app.api.routes.get_inference_client", return_value=mock_client), \
             patch("app.api.routes.generate_candidates", AsyncMock(return_value=local_candidates)), \
             patch("app.api.routes.get_latent_mapper", return_value=mock_mapper), \
             patch("app.api.routes.fetch_product_metadata", AsyncMock(return_value=mock_metadata)), \
             patch("app.api.routes.apply_all_rules", AsyncMock(return_value=[fake_uuid])):

            response = await get_recommendations(user_id="user_test", k=10)

        # Verified fallback occurred safely
        self.assertTrue("popularity" in response.strategy_used)
        self.assertEqual(len(response.recommendations), 1)
        self.assertEqual(response.recommendations[0].product_id, fake_uuid)


    async def test_route_product_id_numeric_calls_external_ml(self):
        """When product_id is a numeric string or integer, it is passed directly to external ML."""
        from app.api.routes import get_recommendations

        fake_uuid = uuid4()
        mock_inference_response = InferenceResponse(
            status="success",
            items=[InferredItem(item_id=2001, score=0.92)],
            strategy_used="two_stage_item_sim_lgbm",
            model_version="production_v1"
        )

        mock_client = AsyncMock()
        mock_client.infer = AsyncMock(return_value=mock_inference_response)

        mock_mapper = AsyncMock()
        mock_mapper.map_to_catalog = AsyncMock(return_value=[(fake_uuid, 2001)])

        mock_metadata = {
            fake_uuid: {"name": "Similar Product", "price": 19.99, "category_name": "Electronics"}
        }

        with patch("app.api.routes.settings.ml_inference_enabled", True), \
             patch("app.api.routes.settings.ml_inference_url", "http://mock-ml:8001"), \
             patch("app.api.routes.get_inference_client", return_value=mock_client), \
             patch("app.api.routes.get_latent_mapper", return_value=mock_mapper), \
             patch("app.api.routes.fetch_product_metadata", AsyncMock(return_value=mock_metadata)), \
             patch("app.api.routes.apply_all_rules", AsyncMock(return_value=[fake_uuid])):

            response = await get_recommendations(product_id="445351", k=8)

        mock_client.infer.assert_called_once_with(
            user_id=None,
            item_id=445351,
            k=settings.candidate_pool_size,
            model_version=getattr(settings, "model_version", None)
        )
        self.assertEqual(response.strategy_used, "two_stage_item_sim_lgbm")
        self.assertEqual(len(response.recommendations), 1)

    async def test_route_product_id_catalog_uuid_reverse_maps_and_calls_external_ml(self):
        """When product_id is a catalog UUID, it is reverse-mapped to latent_item_id before calling external ML."""
        from app.api.routes import get_recommendations
        from uuid import UUID

        catalog_uuid = UUID("0d9d2060-38a5-55ef-9b70-a51baa2947f4")
        rec_uuid = uuid4()

        mock_inference_response = InferenceResponse(
            status="success",
            items=[InferredItem(item_id=12345, score=0.91)],
            strategy_used="two_stage_item_sim_lgbm",
            model_version="production_v1"
        )

        mock_client = AsyncMock()
        mock_client.infer = AsyncMock(return_value=mock_inference_response)

        mock_mapper = AsyncMock()
        mock_mapper.get_latent_id_for_product = AsyncMock(return_value=445351)
        mock_mapper.map_to_catalog = AsyncMock(return_value=[(rec_uuid, 12345)])

        mock_metadata = {
            rec_uuid: {"name": "Recommended Product", "price": 49.99, "category_name": "Gadgets"}
        }

        with patch("app.api.routes.settings.ml_inference_enabled", True), \
             patch("app.api.routes.settings.ml_inference_url", "http://mock-ml:8001"), \
             patch("app.api.routes.get_inference_client", return_value=mock_client), \
             patch("app.api.routes.get_latent_mapper", return_value=mock_mapper), \
             patch("app.api.routes.fetch_product_metadata", AsyncMock(return_value=mock_metadata)), \
             patch("app.api.routes.apply_all_rules", AsyncMock(return_value=[rec_uuid])):

            response = await get_recommendations(product_id=catalog_uuid, k=8)

        mock_mapper.get_latent_id_for_product.assert_called_once_with(catalog_uuid)
        mock_client.infer.assert_called_once_with(
            user_id=None,
            item_id=445351,
            k=settings.candidate_pool_size,
            model_version=getattr(settings, "model_version", None)
        )
        self.assertEqual(response.strategy_used, "two_stage_item_sim_lgbm")
        self.assertEqual(len(response.recommendations), 1)

    async def test_route_product_id_unmapped_uuid_falls_back_safely(self):
        """When catalog UUID has no latent mapping, external ML receives item_id=None and falls back safely."""
        from app.api.routes import get_recommendations
        from uuid import UUID

        unmapped_uuid = UUID("11111111-2222-3333-4444-555555555555")
        rec_uuid = uuid4()

        # External ML returns cold start when item_id is None
        mock_inference_response = InferenceResponse(
            status="cold_start",
            items=[],
            strategy_used="empty_context",
            model_version="production_v1"
        )

        mock_client = AsyncMock()
        mock_client.infer = AsyncMock(return_value=mock_inference_response)

        mock_mapper = AsyncMock()
        mock_mapper.get_latent_id_for_product = AsyncMock(return_value=None)
        mock_mapper.map_to_catalog = AsyncMock(return_value=[(rec_uuid, 9999)])
        mock_mapper.get_valid_latent_ids = AsyncMock(return_value=[9999])

        mock_metadata = {
            rec_uuid: {"name": "Popular Product", "price": 15.00, "category_name": "General"}
        }

        local_candidates = ("popularity", [(9999, 0.4)])

        with patch("app.api.routes.settings.ml_inference_enabled", True), \
             patch("app.api.routes.settings.ml_inference_url", "http://mock-ml:8001"), \
             patch("app.api.routes.get_inference_client", return_value=mock_client), \
             patch("app.api.routes.get_latent_mapper", return_value=mock_mapper), \
             patch("app.api.routes.generate_candidates", AsyncMock(return_value=local_candidates)), \
             patch("app.api.routes.fetch_product_metadata", AsyncMock(return_value=mock_metadata)), \
             patch("app.api.routes.apply_all_rules", AsyncMock(return_value=[rec_uuid])):

            response = await get_recommendations(product_id=unmapped_uuid, k=8)

        mock_mapper.get_latent_id_for_product.assert_called_once_with(unmapped_uuid)
        mock_client.infer.assert_called_once_with(
            user_id=None,
            item_id=None,
            k=settings.candidate_pool_size,
            model_version=getattr(settings, "model_version", None)
        )
        self.assertTrue("popularity" in response.strategy_used)
        self.assertEqual(len(response.recommendations), 1)

    async def test_route_external_ml_candidates_unmapped_in_db_falls_back_to_local_pipeline(self):
        """When external ML returns candidates but none exist in latent_item_mappings, route falls back safely."""
        from app.api.routes import get_recommendations
        from uuid import UUID

        catalog_uuid = UUID("0d9d2060-38a5-55ef-9b70-a51baa2947f4")
        fallback_uuid = uuid4()

        # OCI ML returns 36 candidate items
        mock_inference_response = InferenceResponse(
            status="success",
            items=[InferredItem(item_id=i, score=0.9 - i * 0.01) for i in range(1001, 1037)],
            strategy_used="two_stage_item_sim_lgbm",
            model_version="production_v1"
        )

        mock_client = AsyncMock()
        mock_client.infer = AsyncMock(return_value=mock_inference_response)

        mock_mapper = AsyncMock()
        mock_mapper.get_latent_id_for_product = AsyncMock(return_value=445351)
        # Database has NO mappings for these 36 candidates
        mock_mapper.map_to_catalog = AsyncMock(return_value=[])

        # Local pipeline fallback returns category similarity
        local_candidates = ("category_similarity", [fallback_uuid], True)

        mock_metadata = {
            fallback_uuid: {"name": "Category Fallback Product", "price": 24.99, "category_name": "Electronics"}
        }

        with patch("app.api.routes.settings.ml_inference_enabled", True), \
             patch("app.api.routes.settings.ml_inference_url", "http://mock-ml:8001"), \
             patch("app.api.routes.get_inference_client", return_value=mock_client), \
             patch("app.api.routes.get_latent_mapper", return_value=mock_mapper), \
             patch("app.api.routes.generate_candidates", AsyncMock(return_value=local_candidates)), \
             patch("app.api.routes.fetch_product_metadata", AsyncMock(return_value=mock_metadata)), \
             patch("app.api.routes.apply_all_rules", AsyncMock(return_value=[fallback_uuid])):

            response = await get_recommendations(product_id=catalog_uuid, k=8)

        # Verified it did NOT return empty recommendations with two_stage_item_sim_lgbm
        self.assertEqual(response.strategy_used, "category_similarity")
        self.assertEqual(len(response.recommendations), 1)
        self.assertEqual(response.recommendations[0].product_id, fallback_uuid)


class TestReverseLatentMapping(unittest.IsolatedAsyncioTestCase):
    """Test LatentMapper reverse lookup method."""

    async def test_get_latent_id_for_product_success(self):
        from app.mapping.latent_mapper import LatentMapper
        from uuid import UUID

        mapper = LatentMapper()
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={"latent_item_id": 445351})

        # Mock pool.acquire context manager
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
        mock_pool.acquire.return_value.__aexit__.return_value = None
        mapper.pool = mock_pool

        test_uuid = UUID("0d9d2060-38a5-55ef-9b70-a51baa2947f4")
        latent_id = await mapper.get_latent_id_for_product(test_uuid)

        self.assertEqual(latent_id, 445351)
        mock_conn.fetchrow.assert_called_once()

    async def test_get_latent_id_for_product_string_uuid(self):
        from app.mapping.latent_mapper import LatentMapper
        from uuid import UUID

        mapper = LatentMapper()
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={"latent_item_id": 445351})

        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
        mock_pool.acquire.return_value.__aexit__.return_value = None
        mapper.pool = mock_pool

        latent_id = await mapper.get_latent_id_for_product("0d9d2060-38a5-55ef-9b70-a51baa2947f4")

        self.assertEqual(latent_id, 445351)

    async def test_get_latent_id_for_product_unmapped_returns_none(self):
        from app.mapping.latent_mapper import LatentMapper
        from uuid import UUID

        mapper = LatentMapper()
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)

        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
        mock_pool.acquire.return_value.__aexit__.return_value = None
        mapper.pool = mock_pool

        latent_id = await mapper.get_latent_id_for_product(UUID("11111111-2222-3333-4444-555555555555"))
        self.assertIsNone(latent_id)

    async def test_get_latent_id_for_product_invalid_uuid_returns_none(self):
        from app.mapping.latent_mapper import LatentMapper

        mapper = LatentMapper()
        mapper.pool = MagicMock()

        self.assertIsNone(await mapper.get_latent_id_for_product("invalid-uuid-string"))
        self.assertIsNone(await mapper.get_latent_id_for_product(None))


def run_tests():
    """Run test suite."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestMLInferenceSchemas))
    suite.addTests(loader.loadTestsFromTestCase(TestMLInferenceClient))
    suite.addTests(loader.loadTestsFromTestCase(TestRecommendationRouteWithExternalML))
    suite.addTests(loader.loadTestsFromTestCase(TestReverseLatentMapping))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_tests())
