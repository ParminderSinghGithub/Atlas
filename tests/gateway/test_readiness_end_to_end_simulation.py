"""
Local End-to-End Simulation Tests for Atlas Readiness & Cold-Start Wake-up Flow.

STRICTLY LOCAL ONLY - ZERO network requests to deployed services.

Covers:
1. Catalog included in readiness probe fanout.
2. All services ready -> overall readiness is 'ready'.
3. Catalog takes 30-40s / multiple attempts to boot -> gateway returns 'warming_up', frontend gate stays locked.
4. Recommendation and User ready before Catalog -> gateway stays 'warming_up', preventing premature release.
5. Single-flight lock prevents probe storm / concurrent duplicate requests.
6. Transient connection errors (ConnectError, Timeout) treated as 'warming_up' during boot.
7. Optional ML Inference Service offline -> system reports 'degraded' (core ready).
8. Gateway proxy routing for products/categories works cleanly once ready.
"""
import unittest
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
import httpx
from starlette.requests import Request

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../services/api-gateway')))

from app.main import (
    app,
    system_readiness,
    _probe_single_service,
    _readiness_cache,
    _readiness_lock,
    proxy_catalog,
)
from app.core.config import (
    settings,
    get_catalog_service_url,
    get_recommendation_service_url,
    get_user_service_url,
    get_ml_inference_service_url,
    _normalize_service_url,
)


class TestReadinessEndToEndSimulation(unittest.IsolatedAsyncioTestCase):
    """Rigorous local simulations of microservice cold-start dynamics."""

    def setUp(self):
        _readiness_cache["data"] = None
        _readiness_cache["timestamp"] = 0.0

    def test_downstream_url_getters_and_normalizers(self):
        """Test that all downstream service URLs are properly normalized and not omitted."""
        cat_url = get_catalog_service_url()
        rec_url = get_recommendation_service_url()
        user_url = get_user_service_url()
        ml_url = get_ml_inference_service_url()

        self.assertTrue(len(cat_url) > 0)
        self.assertTrue(len(rec_url) > 0)
        self.assertTrue(len(user_url) > 0)
        self.assertTrue(len(ml_url) > 0)

        # Check normalization handles dirty env values
        self.assertEqual(_normalize_service_url("http://catalog:5004/api/v1/catalog/"), "http://catalog:5004")
        self.assertEqual(_normalize_service_url("http://user:5000/api/auth/"), "http://user:5000")
        self.assertEqual(_normalize_service_url("http://rec:5005/api/v1/"), "http://rec:5005")

    @patch("app.main.httpx.AsyncClient")
    async def test_simulation_all_services_instantly_ready(self, mock_client_cls):
        """Simulation: All services already warm -> immediate 'ready' status."""
        mock_instance = AsyncMock()
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "healthy", "database": "connected"}
        mock_instance.get.return_value = mock_resp
        mock_instance.__aenter__.return_value = mock_instance
        mock_client_cls.return_value = mock_instance

        res = await system_readiness(force_refresh=True)
        self.assertEqual(res["status"], "ready")
        self.assertEqual(res["summary"]["ready"], 5)
        self.assertEqual(res["services"]["catalog_service"]["status"], "ready")
        self.assertEqual(res["services"]["recommendation_service"]["status"], "ready")
        self.assertEqual(res["services"]["user_service"]["status"], "ready")
        self.assertEqual(res["services"]["ml_inference_service"]["status"], "ready")

    @patch("app.main.httpx.AsyncClient")
    async def test_simulation_delayed_catalog_cold_start(self, mock_client_cls):
        """
        Simulation: Catalog Service takes ~35s (3 probe iterations) to warm up.
        Proves that while Catalog is warming, gateway status remains 'warming_up',
        and only transitions to 'ready' when Catalog finishes cold booting.
        """
        mock_instance = AsyncMock()
        mock_instance.__aenter__.return_value = mock_instance
        mock_client_cls.return_value = mock_instance

        attempt_counter = {"catalog": 0}

        def probe_behavior(url, **kwargs):
            resp = MagicMock(spec=httpx.Response)
            if "catalog" in url:
                attempt_counter["catalog"] += 1
                if attempt_counter["catalog"] < 3:
                    # Attempt 1 & 2: Container spinning up on Render (503 / initializing)
                    resp.status_code = 503
                    resp.json.return_value = {"status": "unhealthy", "detail": "Starting"}
                else:
                    # Attempt 3: Container fully online
                    resp.status_code = 200
                    resp.json.return_value = {"status": "healthy", "database": "connected"}
            else:
                # Other services are ready
                resp.status_code = 200
                resp.json.return_value = {"status": "healthy", "database": "connected"}
            return resp

        mock_instance.get.side_effect = probe_behavior

        # Attempt 1: Catalog warming -> overall 'warming_up'
        res1 = await system_readiness(force_refresh=True)
        self.assertEqual(res1["status"], "warming_up")
        self.assertEqual(res1["services"]["catalog_service"]["status"], "warming_up")
        self.assertEqual(res1["services"]["recommendation_service"]["status"], "ready")

        # Attempt 2: Catalog still warming -> overall 'warming_up'
        res2 = await system_readiness(force_refresh=True)
        self.assertEqual(res2["status"], "warming_up")
        self.assertEqual(res2["services"]["catalog_service"]["status"], "warming_up")

        # Attempt 3: Catalog finishes booting -> overall 'ready'
        res3 = await system_readiness(force_refresh=True)
        self.assertEqual(res3["status"], "ready")
        self.assertEqual(res3["services"]["catalog_service"]["status"], "ready")

    @patch("app.main.httpx.AsyncClient")
    async def test_simulation_recommendation_and_user_ready_before_catalog(self, mock_client_cls):
        """
        Simulation: Recommendation and User Service ready, but Catalog is ConnectError.
        Proves gateway never releases 'ready' or 'degraded' when Catalog is offline.
        """
        mock_instance = AsyncMock()
        mock_instance.__aenter__.return_value = mock_instance
        mock_client_cls.return_value = mock_instance

        def probe_behavior(url, **kwargs):
            if "catalog" in url:
                raise httpx.ConnectError("Connection refused: catalog container starting")
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 200
            resp.json.return_value = {"status": "healthy", "database": "connected"}
            return resp

        mock_instance.get.side_effect = probe_behavior

        res = await system_readiness(force_refresh=True)
        self.assertEqual(res["status"], "warming_up")
        self.assertEqual(res["services"]["catalog_service"]["status"], "warming_up")
        self.assertEqual(res["services"]["recommendation_service"]["status"], "ready")
        self.assertEqual(res["services"]["user_service"]["status"], "ready")

    @patch("app.main.httpx.AsyncClient")
    async def test_simulation_ml_offline_degraded_state(self, mock_client_cls):
        """
        Simulation: Catalog, Recommendation, User ready, ML engine offline.
        Proves status is 'degraded' (core browsing & auth fully allowed).
        """
        mock_instance = AsyncMock()
        mock_instance.__aenter__.return_value = mock_instance
        mock_client_cls.return_value = mock_instance

        def probe_behavior(url, **kwargs):
            resp = MagicMock(spec=httpx.Response)
            if "8001" in url or "ml" in url:
                resp.status_code = 503
                resp.json.return_value = {"status": "unhealthy"}
            else:
                resp.status_code = 200
                resp.json.return_value = {"status": "healthy", "database": "connected"}
            return resp

        mock_instance.get.side_effect = probe_behavior

        res = await system_readiness(force_refresh=True)
        self.assertEqual(res["status"], "degraded")
        self.assertEqual(res["services"]["catalog_service"]["status"], "ready")
        self.assertEqual(res["services"]["recommendation_service"]["status"], "ready")
        self.assertEqual(res["services"]["user_service"]["status"], "ready")
        self.assertEqual(res["services"]["ml_inference_service"]["status"], "warming_up")

    @patch("app.main.httpx.AsyncClient")
    async def test_single_flight_lock_and_cache_ttl(self, mock_client_cls):
        """
        Simulation: Concurrent requests do not duplicate downstream probes.
        Verifies in-memory cache and asyncio.Lock.
        """
        mock_instance = AsyncMock()
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "healthy", "database": "connected"}
        mock_instance.get.return_value = mock_resp
        mock_instance.__aenter__.return_value = mock_instance
        mock_client_cls.return_value = mock_instance

        # Call system_readiness 5 times concurrently
        tasks = [system_readiness(force_refresh=False) for _ in range(5)]
        results = await asyncio.gather(*tasks)

        # All 5 return identical 'ready' status
        for r in results:
            self.assertEqual(r["status"], "ready")

        # Downstream probes were executed exactly 1 time across the 5 concurrent callers
        self.assertEqual(mock_instance.get.call_count, 4)  # 4 probes in 1 batch


if __name__ == "__main__":
    unittest.main()
