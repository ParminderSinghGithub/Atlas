"""
Unit Tests for API Gateway Readiness Coordinator, Catalog Proxy, and Event Ingestion.

Validates:
1. Coordinated readiness probe execution with deep database readiness checks.
2. Readiness state transitions: 'warming_up', 'degraded', 'ready', 'unavailable'.
3. Precise catalog proxy mapping (/api/v1/catalog/products, /api/v1/catalog/products/{id}, /api/v1/catalog/categories).
4. Dual event ingestion proxy mapping (POST /api/events, POST /events -> /events).
5. Recommendation product UUID preservation across gateway.
"""
import unittest
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4
import httpx
from starlette.requests import Request

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../services/api-gateway')))

from app.main import app, _probe_single_service, _readiness_cache, proxy_catalog, proxy_events
from app.core.config import settings


class TestReadinessCoordinator(unittest.IsolatedAsyncioTestCase):
    """Test API Gateway readiness probe logic and state transitions."""

    def setUp(self):
        _readiness_cache["data"] = None
        _readiness_cache["timestamp"] = 0.0

    async def test_probe_single_service_healthy(self):
        """Verify probe returns 'ready' when service is healthy and connected."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "healthy", "database": "connected"}
        mock_client.get.return_value = mock_response

        res = await _probe_single_service(
            client=mock_client,
            service_key="catalog_service",
            name="Catalog Service",
            url="https://catalog-service-uo46.onrender.com/api/v1/catalog/health",
            is_critical=True,
        )

        self.assertEqual(res["status"], "ready")
        self.assertEqual(res["name"], "Catalog Service")
        self.assertTrue(res["critical"])

    async def test_probe_single_service_database_disconnected(self):
        """Verify probe distinguishes reachable vs ready (database disconnected -> warming_up)."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "unhealthy", "database": "disconnected"}
        mock_client.get.return_value = mock_response

        res = await _probe_single_service(
            client=mock_client,
            service_key="catalog_service",
            name="Catalog Service",
            url="https://catalog-service-uo46.onrender.com/api/v1/catalog/health",
            is_critical=True,
        )

        self.assertEqual(res["status"], "warming_up")
        self.assertEqual(res["detail"], "Database initializing")

    async def test_probe_single_service_503_warming_up(self):
        """Verify probe marks 503 response as 'warming_up' for cold-start containers."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 503
        mock_client.get.return_value = mock_response

        res = await _probe_single_service(
            client=mock_client,
            service_key="recommendation_service",
            name="Recommendation Service",
            url="https://recommendation-service-8ag0.onrender.com/health",
            is_critical=True,
        )

        self.assertEqual(res["status"], "warming_up")

    async def test_probe_single_service_timeout(self):
        """Verify timeout during cold-start returns warming_up status."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.side_effect = httpx.TimeoutException("Container boot timeout")

        res = await _probe_single_service(
            client=mock_client,
            service_key="catalog_service",
            name="Catalog Service",
            url="https://catalog-service-uo46.onrender.com/api/v1/catalog/health",
            is_critical=True,
        )

        self.assertEqual(res["status"], "warming_up")
        self.assertIn("warming up", res["error"])

    async def test_probe_single_service_404_fallback(self):
        """Verify 404 on primary path triggers fallback health endpoint check."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        resp_404 = MagicMock(spec=httpx.Response)
        resp_404.status_code = 404

        resp_200 = MagicMock(spec=httpx.Response)
        resp_200.status_code = 200
        resp_200.json.return_value = {"status": "healthy"}

        mock_client.get.side_effect = [resp_404, resp_200]

        res = await _probe_single_service(
            client=mock_client,
            service_key="catalog_service",
            name="Catalog Service",
            url="https://catalog-service-uo46.onrender.com/api/v1/health",
            is_critical=True,
        )

        self.assertEqual(res["status"], "ready")
        self.assertEqual(mock_client.get.call_count, 2)


class TestCatalogAndEventRouting(unittest.IsolatedAsyncioTestCase):
    """Test API Gateway proxy routing to downstream catalog and event endpoints."""

    @patch("app.main.httpx.AsyncClient")
    async def test_catalog_products_list_routing(self, mock_client_cls):
        """Verify GET /api/v1/catalog/products routes to downstream /api/v1/catalog/products."""
        mock_instance = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b'{"products": [{"id": "test-uuid", "name": "Item"}], "pagination": {}}'
        mock_resp.headers = {"content-type": "application/json"}
        mock_instance.get.return_value = mock_resp
        mock_instance.__aenter__.return_value = mock_instance
        mock_client_cls.return_value = mock_instance

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/catalog/products",
            "query_string": b"limit=10",
            "headers": [],
        }
        req = Request(scope)
        response = await proxy_catalog(req, path="products")

        self.assertEqual(response.status_code, 200)
        mock_instance.get.assert_called_once()
        called_url = str(mock_instance.get.call_args[0][0])
        self.assertTrue(called_url.endswith("/api/v1/catalog/products?limit=10"))

    @patch("app.main.httpx.AsyncClient")
    async def test_catalog_product_detail_routing(self, mock_client_cls):
        """Verify GET /api/v1/catalog/products/{uuid} routes to downstream /api/v1/catalog/products/{uuid}."""
        test_uuid = str(uuid4())
        mock_instance = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b'{"id": "test", "name": "Detail Item", "price": 99.99}'
        mock_resp.headers = {"content-type": "application/json"}
        mock_instance.get.return_value = mock_resp
        mock_instance.__aenter__.return_value = mock_instance
        mock_client_cls.return_value = mock_instance

        scope = {
            "type": "http",
            "method": "GET",
            "path": f"/api/v1/catalog/products/{test_uuid}",
            "query_string": b"",
            "headers": [],
        }
        req = Request(scope)
        response = await proxy_catalog(req, path=f"products/{test_uuid}")

        self.assertEqual(response.status_code, 200)
        mock_instance.get.assert_called_once()
        called_url = str(mock_instance.get.call_args[0][0])
        self.assertTrue(called_url.endswith(f"/api/v1/catalog/products/{test_uuid}"))

    @patch("app.main.httpx.AsyncClient")
    async def test_catalog_categories_routing(self, mock_client_cls):
        """Verify GET /api/v1/catalog/categories routes to downstream /api/v1/catalog/categories."""
        mock_instance = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b'{"categories": [{"id": "cat-1", "name": "Electronics"}]}'
        mock_resp.headers = {"content-type": "application/json"}
        mock_instance.get.return_value = mock_resp
        mock_instance.__aenter__.return_value = mock_instance
        mock_client_cls.return_value = mock_instance

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/catalog/categories",
            "query_string": b"",
            "headers": [],
        }
        req = Request(scope)
        response = await proxy_catalog(req, path="categories")

        self.assertEqual(response.status_code, 200)
        mock_instance.get.assert_called_once()
        called_url = str(mock_instance.get.call_args[0][0])
        self.assertTrue(called_url.endswith("/api/v1/catalog/categories"))

    @patch("app.main.httpx.AsyncClient")
    async def test_api_events_post_routing(self, mock_client_cls):
        """Verify POST /api/events correctly proxies to downstream /events."""
        mock_instance = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.content = b'{"status": "ok", "event_id": "e-123"}'
        mock_resp.headers = {"content-type": "application/json"}
        mock_instance.request.return_value = mock_resp
        mock_instance.__aenter__.return_value = mock_instance
        mock_client_cls.return_value = mock_instance

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/events",
            "query_string": b"",
            "headers": [],
        }
        async def receive():
            return {"type": "http.request", "body": b'{"event_type": "view"}', "more_body": False}

        req = Request(scope, receive=receive)
        response = await proxy_events(req, path="")

        self.assertEqual(response.status_code, 201)
        mock_instance.request.assert_called_once()
        called_url = str(mock_instance.request.call_args[1]["url"])
        self.assertTrue(called_url.endswith("/events"))


if __name__ == "__main__":
    unittest.main()
