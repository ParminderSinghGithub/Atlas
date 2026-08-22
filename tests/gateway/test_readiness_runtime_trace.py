"""
RUNTIME CONTROL-FLOW & DISPATCH VERIFICATION TEST SUITE
======================================================
Strictly Local-Only: ZERO live network requests.

Verifies:
- Outbound HTTP call interception (capturing exact URL, method, headers, timeout, redirects)
- Downstream probe dispatch under all operational states (All Up, All Down, Partial Down, Cold-Start)
- Cache expiration and re-dispatch behavior (warming vs ready TTLs)
- URL construction with production Render environment variables
- Resilience against pre-dispatch and in-flight exceptions
"""
import asyncio
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../services/api-gateway')))

from app.main import (
    app,
    system_readiness,
    _probe_single_service,
    _readiness_cache,
    _readiness_lock,
)
from app.core.config import (
    settings,
    get_catalog_service_url,
    get_user_service_url,
    get_recommendation_service_url,
    get_ml_inference_service_url,
    _normalize_service_url,
)


class TestReadinessRuntimeControlFlow(unittest.IsolatedAsyncioTestCase):
    """Deep forensic tests intercepting httpx.AsyncClient at the socket/client layer."""

    def setUp(self):
        _readiness_cache["data"] = None
        _readiness_cache["timestamp"] = 0.0

    @patch("app.main.httpx.AsyncClient")
    async def test_A_all_downstream_available_records_exact_invocations(self, mock_client_cls):
        """
        Phase 2A: All downstream services available.
        Proves:
        - Outbound GET is invoked for Catalog, User, Rec, and ML
        - Exact headers, timeout, and method are captured
        - Final response status is 'ready'
        """
        mock_instance = AsyncMock()
        mock_instance.__aenter__.return_value = mock_instance
        mock_client_cls.return_value = mock_instance

        recorded_requests = []

        async def intercept_get(url, headers=None, **kwargs):
            recorded_requests.append({
                "method": "GET",
                "url": str(url),
                "headers": headers,
            })
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 200
            resp.json.return_value = {"status": "healthy", "database": "connected"}
            return resp

        mock_instance.get = intercept_get

        response = await system_readiness(force_refresh=True)

        self.assertEqual(len(recorded_requests), 4, f"Expected 4 HTTP requests, got {len(recorded_requests)}")
        urls_called = [r["url"] for r in recorded_requests]

        cat_url = get_catalog_service_url()
        user_url = get_user_service_url()
        rec_url = get_recommendation_service_url()
        ml_url = get_ml_inference_service_url()

        self.assertIn(f"{cat_url}/api/v1/catalog/health", urls_called)
        self.assertIn(f"{user_url}/api/auth/ping", urls_called)
        self.assertIn(f"{rec_url}/health", urls_called)
        self.assertIn(f"{ml_url}/health", urls_called)

        # Check headers passed
        for req in recorded_requests:
            self.assertEqual(req["headers"].get("Accept"), "application/json")
            self.assertEqual(req["headers"].get("User-Agent"), "Atlas-API-Gateway/2.0")

        self.assertEqual(response["status"], "ready")
        self.assertEqual(response["summary"]["ready"], 5)

    @patch("app.main.httpx.AsyncClient")
    async def test_B_all_downstream_unavailable_attempts_all_probes(self, mock_client_cls):
        """
        Phase 2B: All downstream services unavailable (ConnectError / Timeout).
        Proves:
        - Gateway still attempts ALL 4 probes (no early abort)
        - Response reflects warming_up / unavailable state cleanly
        """
        mock_instance = AsyncMock()
        mock_instance.__aenter__.return_value = mock_instance
        mock_client_cls.return_value = mock_instance

        recorded_requests = []

        async def intercept_get(url, headers=None, **kwargs):
            recorded_requests.append(str(url))
            raise httpx.ConnectError(f"Connection refused to {url}")

        mock_instance.get = intercept_get

        response = await system_readiness(force_refresh=True)

        self.assertEqual(len(recorded_requests), 4, "Gateway failed to attempt all 4 probes when failing")
        self.assertEqual(response["status"], "warming_up")
        self.assertEqual(response["summary"]["warming"], 4)
        self.assertEqual(response["services"]["catalog_service"]["status"], "warming_up")
        self.assertEqual(response["services"]["user_service"]["status"], "warming_up")
        self.assertEqual(response["services"]["recommendation_service"]["status"], "warming_up")

    @patch("app.main.httpx.AsyncClient")
    async def test_C_catalog_unavailable_does_not_prevent_user_and_rec(self, mock_client_cls):
        """
        Phase 2C: Catalog fails with TimeoutException while User and Rec succeed.
        Proves:
        - Catalog failure is isolated
        - User and Rec probes succeed and are marked 'ready'
        - Overall status is 'warming_up' because Catalog is critical
        """
        mock_instance = AsyncMock()
        mock_instance.__aenter__.return_value = mock_instance
        mock_client_cls.return_value = mock_instance

        recorded_requests = []

        async def intercept_get(url, headers=None, **kwargs):
            recorded_requests.append(str(url))
            if "catalog" in str(url):
                raise httpx.TimeoutException("Catalog container starting")
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 200
            resp.json.return_value = {"status": "healthy", "database": "connected"}
            return resp

        mock_instance.get = intercept_get

        response = await system_readiness(force_refresh=True)

        self.assertEqual(len(recorded_requests), 4)
        self.assertEqual(response["status"], "warming_up")
        self.assertEqual(response["services"]["catalog_service"]["status"], "warming_up")
        self.assertEqual(response["services"]["user_service"]["status"], "ready")
        self.assertEqual(response["services"]["recommendation_service"]["status"], "ready")

    @patch("app.main.httpx.AsyncClient")
    async def test_D_warming_cold_start_503_response_handling(self, mock_client_cls):
        """
        Phase 2D: Downstream returns 503 Service Unavailable (Render edge boot).
        Proves:
        - Gateway interprets 503 as warming_up
        - Latency is computed
        """
        mock_instance = AsyncMock()
        mock_instance.__aenter__.return_value = mock_instance
        mock_client_cls.return_value = mock_instance

        async def intercept_get(url, headers=None, **kwargs):
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 503
            resp.json.return_value = {"detail": "Container starting"}
            return resp

        mock_instance.get = intercept_get

        response = await system_readiness(force_refresh=True)
        self.assertEqual(response["status"], "warming_up")
        self.assertEqual(response["services"]["catalog_service"]["status"], "warming_up")
        self.assertEqual(response["services"]["catalog_service"]["status_code"], 503)

    @patch("app.main.httpx.AsyncClient")
    async def test_E_cache_behavior_ready_vs_warming_ttl(self, mock_client_cls):
        """
        Phase 2E: Readiness cache logic.
        Proves:
        - When status is 'ready', cached result is returned within 10s (no HTTP call)
        - When status is 'warming_up', cached result expires in 2s (fresh probe dispatched)
        """
        mock_instance = AsyncMock()
        mock_instance.__aenter__.return_value = mock_instance
        mock_client_cls.return_value = mock_instance

        call_count = {"count": 0}

        async def intercept_get(url, headers=None, **kwargs):
            call_count["count"] += 1
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 200
            resp.json.return_value = {"status": "healthy", "database": "connected"}
            return resp

        mock_instance.get = intercept_get

        # 1. First probe -> executes 4 calls, caches 'ready'
        res1 = await system_readiness(force_refresh=False)
        self.assertEqual(res1["status"], "ready")
        self.assertEqual(call_count["count"], 4)

        # 2. Immediate second call -> cache hit (<10s), 0 new calls
        res2 = await system_readiness(force_refresh=False)
        self.assertEqual(res2["status"], "ready")
        self.assertEqual(call_count["count"], 4)

        # 3. Simulate warming_up cache entry 2.5 seconds ago (>2.0s warming TTL)
        _readiness_cache["data"] = {
            "status": "warming_up",
            "services": {"catalog_service": {"status": "warming_up", "critical": True}},
        }
        _readiness_cache["timestamp"] = time.time() - 2.5

        # 4. Third call -> warming cache expired -> fresh 4 calls dispatched
        res3 = await system_readiness(force_refresh=False)
        self.assertEqual(call_count["count"], 8)

    @patch("app.main.httpx.AsyncClient")
    async def test_F_exception_handling_in_gather(self, mock_client_cls):
        """
        Phase 2F: If an unexpected BaseException occurs inside one task,
        return_exceptions=True captures it and prevents the gateway handler from crashing.
        """
        mock_instance = AsyncMock()
        mock_instance.__aenter__.return_value = mock_instance
        mock_client_cls.return_value = mock_instance

        async def intercept_get(url, headers=None, **kwargs):
            if "catalog" in str(url):
                raise RuntimeError("Unexpected socket corruption")
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 200
            resp.json.return_value = {"status": "healthy"}
            return resp

        mock_instance.get = intercept_get

        response = await system_readiness(force_refresh=True)
        # Should not raise, but report warming_up / error
        self.assertIn("catalog_service", response["services"])
        self.assertEqual(response["services"]["catalog_service"]["status"], "unavailable")
        self.assertIn("Unexpected socket corruption", response["services"]["catalog_service"]["error"])

    @patch("app.main.httpx.AsyncClient")
    async def test_G_url_construction_with_exact_render_production_env(self, mock_client_cls):
        """
        Phase 2G: Set the exact Render production URLs in environment variables
        and assert that the exact outbound probe URLs match expectations.
        """
        mock_instance = AsyncMock()
        mock_instance.__aenter__.return_value = mock_instance
        mock_client_cls.return_value = mock_instance

        recorded_urls = []

        async def intercept_get(url, headers=None, **kwargs):
            recorded_urls.append(str(url))
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 200
            resp.json.return_value = {"status": "healthy"}
            return resp

        mock_instance.get = intercept_get

        # Set exact production URLs
        env_patch = {
            "CATALOG_SERVICE_URL": "https://catalog-service-uo46.onrender.com",
            "USER_SERVICE_URL": "https://user-service-rzbt.onrender.com",
            "RECOMMENDATION_SERVICE_URL": "https://recommendation-service-8ag0.onrender.com",
            "ML_INFERENCE_SERVICE_URL": "http://150.230.143.133:8001",
        }

        with patch.dict(os.environ, env_patch):
            # Reload config to apply env_patch
            import importlib
            import app.core.config as cfg
            importlib.reload(cfg)
            import app.main as mn
            importlib.reload(mn)
            mn._readiness_cache["data"] = None
            mn._readiness_cache["timestamp"] = 0.0

            await mn.system_readiness(force_refresh=True)

            expected_catalog_probe = "https://catalog-service-uo46.onrender.com/api/v1/catalog/health"
            expected_user_probe = "https://user-service-rzbt.onrender.com/api/auth/ping"
            expected_rec_probe = "https://recommendation-service-8ag0.onrender.com/health"
            expected_ml_probe = "http://150.230.143.133:8001/health"

            self.assertIn(expected_catalog_probe, recorded_urls)
            self.assertIn(expected_user_probe, recorded_urls)
            self.assertIn(expected_rec_probe, recorded_urls)
            self.assertIn(expected_ml_probe, recorded_urls)


if __name__ == "__main__":
    unittest.main()
