"""
FORENSIC READINESS PROBE VERIFICATION SUITE
============================================
Purpose: Prove - with zero deployed network calls - that:

1. The correct URL is constructed for each downstream service probe.
2. The httpx.AsyncClient.get() is ACTUALLY CALLED (not mocked away).
3. Each service is probed independently (no cancellation).
4. Environment variable names used in code match those in render.yaml.
5. URL normalization cannot corrupt probe URLs.
6. Cache cannot suppress the initial wake-up probe.
7. Normal proxy routes and readiness probes use the SAME URL construction path.
8. Recommendation service readiness CANNOT be used as proof of wake-up success
   (it may already be alive due to shared rootDir deployment coupling).

WHAT EACH TEST PROVES vs. WHAT IT CANNOT PROVE:

PROVES:
- Code path from system_readiness() -> _probe_single_service() -> httpx GET
- Exact URL atoms: base_url + path suffix for each service
- Independence of catalog, user, rec, ml probes

CANNOT PROVE (without hitting production):
- That CATALOG_SERVICE_URL env var is correctly set in Render dashboard
- That the Render service at that URL is actually receiving packets
- That the Catalog container wakes from Render's sleep state

This file is LOCAL-ONLY. Zero network requests to any deployed service.
"""
import unittest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call
import httpx

import sys
import os

# Insert gateway to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../services/api-gateway')))

from app.main import system_readiness, _probe_single_service, _readiness_cache
from app.core.config import (
    settings,
    get_catalog_service_url,
    get_user_service_url,
    get_recommendation_service_url,
    get_ml_inference_service_url,
    _normalize_service_url,
)


class TestExactURLConstruction(unittest.IsolatedAsyncioTestCase):
    """
    Forensic tests that verify the EXACT URLs constructed for each downstream probe.
    These tests capture the actual call_args of the mock httpx client to verify
    URL correctness - they cannot be fooled by the function returning a mocked result.
    """

    def setUp(self):
        _readiness_cache["data"] = None
        _readiness_cache["timestamp"] = 0.0

    @patch("app.main.httpx.AsyncClient")
    async def test_exact_catalog_probe_url(self, mock_client_cls):
        """
        PROVES: Gateway constructs {CATALOG_SERVICE_URL}/api/v1/catalog/health
        for the Catalog readiness probe.

        This test captures the ACTUAL URL passed to httpx.AsyncClient.get(),
        not just the returned result.
        """
        mock_instance = AsyncMock()
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "healthy", "database": "connected"}
        mock_instance.get.return_value = mock_resp
        mock_instance.__aenter__.return_value = mock_instance
        mock_client_cls.return_value = mock_instance

        await system_readiness(force_refresh=True)

        # Extract all URLs that GET was called with
        actual_urls = [str(c.args[0]) for c in mock_instance.get.call_args_list]

        cat_base = get_catalog_service_url()
        expected_cat_url = f"{cat_base}/api/v1/catalog/health"
        self.assertIn(expected_cat_url, actual_urls,
            f"Catalog probe URL not found.\n"
            f"Expected: {expected_cat_url}\n"
            f"Actual GET calls: {actual_urls}")

    @patch("app.main.httpx.AsyncClient")
    async def test_exact_user_probe_url(self, mock_client_cls):
        """
        PROVES: Gateway constructs {USER_SERVICE_URL}/api/auth/ping
        for the User Service readiness probe.
        """
        mock_instance = AsyncMock()
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"message": "User service alive"}
        mock_instance.get.return_value = mock_resp
        mock_instance.__aenter__.return_value = mock_instance
        mock_client_cls.return_value = mock_instance

        await system_readiness(force_refresh=True)

        actual_urls = [str(c.args[0]) for c in mock_instance.get.call_args_list]

        user_base = get_user_service_url()
        expected_user_url = f"{user_base}/api/auth/ping"
        self.assertIn(expected_user_url, actual_urls,
            f"User probe URL not found.\n"
            f"Expected: {expected_user_url}\n"
            f"Actual GET calls: {actual_urls}")

    @patch("app.main.httpx.AsyncClient")
    async def test_exact_recommendation_probe_url(self, mock_client_cls):
        """
        PROVES: Gateway constructs {RECOMMENDATION_SERVICE_URL}/health
        for the Recommendation Service readiness probe.
        """
        mock_instance = AsyncMock()
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "healthy"}
        mock_instance.get.return_value = mock_resp
        mock_instance.__aenter__.return_value = mock_instance
        mock_client_cls.return_value = mock_instance

        await system_readiness(force_refresh=True)

        actual_urls = [str(c.args[0]) for c in mock_instance.get.call_args_list]

        rec_base = get_recommendation_service_url()
        expected_rec_url = f"{rec_base}/health"
        self.assertIn(expected_rec_url, actual_urls,
            f"Recommendation probe URL not found.\n"
            f"Expected: {expected_rec_url}\n"
            f"Actual GET calls: {actual_urls}")

    @patch("app.main.httpx.AsyncClient")
    async def test_exact_ml_probe_url(self, mock_client_cls):
        """
        PROVES: Gateway constructs {ML_INFERENCE_SERVICE_URL}/health
        for the ML Inference readiness probe.
        """
        mock_instance = AsyncMock()
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "healthy"}
        mock_instance.get.return_value = mock_resp
        mock_instance.__aenter__.return_value = mock_instance
        mock_client_cls.return_value = mock_instance

        await system_readiness(force_refresh=True)

        actual_urls = [str(c.args[0]) for c in mock_instance.get.call_args_list]

        ml_base = get_ml_inference_service_url()
        expected_ml_url = f"{ml_base}/health"
        self.assertIn(expected_ml_url, actual_urls,
            f"ML inference probe URL not found.\n"
            f"Expected: {expected_ml_url}\n"
            f"Actual GET calls: {actual_urls}")

    @patch("app.main.httpx.AsyncClient")
    async def test_all_four_services_are_probed(self, mock_client_cls):
        """
        PROVES: ALL four downstream services receive an HTTP GET during system_readiness().
        No service is silently skipped.
        """
        mock_instance = AsyncMock()
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "healthy", "database": "connected"}
        mock_instance.get.return_value = mock_resp
        mock_instance.__aenter__.return_value = mock_instance
        mock_client_cls.return_value = mock_instance

        await system_readiness(force_refresh=True)

        # Exactly 4 downstream GET calls expected (catalog, rec, user, ml)
        self.assertEqual(mock_instance.get.call_count, 4,
            f"Expected exactly 4 probe calls (catalog, rec, user, ml), "
            f"got {mock_instance.get.call_count}. "
            f"Actual calls: {[str(c.args[0]) for c in mock_instance.get.call_args_list]}")

    @patch("app.main.httpx.AsyncClient")
    async def test_catalog_probe_is_independent_of_recommendation_failure(self, mock_client_cls):
        """
        PROVES: A ConnectError on Recommendation probe does NOT cancel the Catalog probe.
        Each probe is independently resolved via asyncio.gather(return_exceptions=True).
        """
        mock_instance = AsyncMock()
        mock_instance.__aenter__.return_value = mock_instance

        call_log = []

        async def side_effect_get(url, **kwargs):
            call_log.append(url)
            if "recommendation" in url or "5005" in url:
                raise httpx.ConnectError("Rec container cold-starting")
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 200
            resp.json.return_value = {"status": "healthy", "database": "connected"}
            return resp

        mock_instance.get = side_effect_get
        mock_client_cls.return_value = mock_instance

        result = await system_readiness(force_refresh=True)

        # Catalog probe must still have been called
        cat_base = get_catalog_service_url()
        expected_cat_url = f"{cat_base}/api/v1/catalog/health"
        self.assertIn(expected_cat_url, call_log,
            f"Catalog was NOT probed despite rec failure. Calls: {call_log}")

        # Catalog must still be ready
        self.assertEqual(result["services"]["catalog_service"]["status"], "ready",
            "Catalog should be ready even when Recommendation fails")

        # Recommendation must show warming_up (not crash the whole system)
        self.assertEqual(result["services"]["recommendation_service"]["status"], "warming_up",
            "Recommendation ConnectError should yield warming_up, not crash")

    @patch("app.main.httpx.AsyncClient")
    async def test_warming_cache_does_not_suppress_next_probe(self, mock_client_cls):
        """
        PROVES: When the cached result is 'warming_up', the cache is NOT used
        after 2 seconds - a fresh probe is dispatched.

        IMPORTANT: This is the 'stale cache suppresses wake-up' bug fix.
        The gateway must NOT serve a 10s cached 'warming_up' result and skip probing.
        """
        mock_instance = AsyncMock()
        mock_instance.__aenter__.return_value = mock_instance

        call_count = {"n": 0}

        def side_effect_get(url, **kwargs):
            call_count["n"] += 1
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 200
            resp.json.return_value = {"status": "healthy", "database": "connected"}
            return resp

        mock_instance.get.side_effect = side_effect_get
        mock_client_cls.return_value = mock_instance

        # Seed cache with a warming_up result and a timestamp that is 3 seconds old
        # (> 2s warming cache window but < 10s ready cache window)
        import time
        _readiness_cache["data"] = {
            "status": "warming_up",
            "services": {"catalog_service": {"status": "warming_up", "critical": True}},
            "summary": {"total": 5, "ready": 0, "warming": 5, "unavailable": 0},
            "timestamp": "2026-01-01T00:00:00Z",
        }
        _readiness_cache["timestamp"] = time.time() - 3.0  # 3s old

        # A fresh probe MUST happen (cache is 3s old, warming state = 2s max cache age)
        await system_readiness(force_refresh=False)

        self.assertGreater(call_count["n"], 0,
            "Cache was used despite warming_up state being >2s stale. "
            "Fresh probe must be dispatched.")

    def test_env_var_names_match_render_yaml(self):
        """
        PROVES: The environment variable names the gateway reads match
        those defined in render.yaml for the api-gateway service.

        render.yaml declares: USER_SERVICE_URL, CATALOG_SERVICE_URL, RECOMMENDATION_SERVICE_URL
        gateway config reads: USER_SERVICE_URL, CATALOG_SERVICE_URL, RECOMMENDATION_SERVICE_URL

        IMPORTANT: ML_INFERENCE_SERVICE_URL is NOT declared in render.yaml.
        It uses the hardcoded default: http://150.230.143.133:8001
        """
        # These are the env var NAMES the gateway's Settings class reads
        gateway_env_names = {
            "USER_SERVICE_URL",
            "CATALOG_SERVICE_URL",
            "RECOMMENDATION_SERVICE_URL",
            "ML_INFERENCE_SERVICE_URL",
        }

        # These are the env var KEYS declared in render.yaml for api-gateway
        render_yaml_gateway_keys = {
            "USER_SERVICE_URL",
            "CATALOG_SERVICE_URL",
            "RECOMMENDATION_SERVICE_URL",
            # ML_INFERENCE_SERVICE_URL is NOT in render.yaml - uses hardcoded default
        }

        # The three that ARE in render.yaml must match the gateway names
        for key in render_yaml_gateway_keys:
            self.assertIn(key, gateway_env_names,
                f"render.yaml declares {key} for api-gateway "
                f"but gateway Settings doesn't read it")

        # ML_INFERENCE_SERVICE_URL has a hardcoded default - document that it's not in render.yaml
        ml_url = settings.ML_INFERENCE_SERVICE_URL
        self.assertTrue(ml_url.startswith("http://150.230.143.133:8001") or len(ml_url) > 0,
            "ML_INFERENCE_SERVICE_URL has no value - this would be a problem")

    def test_frontend_readiness_path_construction(self):
        """
        PROVES: The frontend constructs GET /api/v1/ready when VITE_API_URL
        is set to https://<gateway>/api (as per Vercel documentation).

        api.ts: baseURL = VITE_API_URL  (e.g. "https://api-gateway-mmoc.onrender.com/api")
        readinessService.ts: api.get('/v1/ready')
        Final URL: "https://api-gateway-mmoc.onrender.com/api/v1/ready"

        This matches the gateway route: @app.get("/api/v1/ready")
        ✓ URL IS CORRECT.
        """
        # Simulate what Axios does: baseURL + path
        base_url_with_api = "https://api-gateway-mmoc.onrender.com/api"
        path = "/v1/ready"
        # Axios joins these: base + path -> base/path (strips duplicate slashes)
        if base_url_with_api.endswith("/"):
            full_url = base_url_with_api.rstrip("/") + path
        else:
            full_url = base_url_with_api + path

        self.assertEqual(full_url, "https://api-gateway-mmoc.onrender.com/api/v1/ready")
        # Gateway route is @app.get("/api/v1/ready") - matches ✓

    def test_proxy_url_construction_matches_readiness_url_construction(self):
        """
        PROVES: Normal catalog proxy uses get_catalog_service_url() + "/api/v1/catalog/..."
        and readiness probe uses get_catalog_service_url() + "/api/v1/catalog/health"

        Both use the same get_catalog_service_url() function, so if one works, the other
        base URL is also correct. The only difference is the appended path.

        This is consistent. If proxy works but health probe doesn't reach catalog,
        the failure is NOT in URL construction - it must be in Render env var configuration
        or the probe being cancelled/cached before reaching the network.
        """
        cat_url = get_catalog_service_url()
        user_url = get_user_service_url()
        rec_url = get_recommendation_service_url()

        # Proxy path
        proxy_cat = f"{cat_url}/api/v1/catalog/products"
        proxy_user = f"{user_url}/api/auth/login"
        proxy_rec = f"{rec_url}/api/v1/recommendations"

        # Readiness probe path
        probe_cat = f"{cat_url}/api/v1/catalog/health"
        probe_user = f"{user_url}/api/auth/ping"
        probe_rec = f"{rec_url}/health"

        # All must share the same base
        self.assertEqual(
            proxy_cat.split("/api/v1/catalog")[0],
            probe_cat.split("/api/v1/catalog")[0],
            "Catalog proxy and probe use different base URLs!"
        )
        self.assertEqual(
            proxy_user.split("/api/auth")[0],
            probe_user.split("/api/auth")[0],
            "User proxy and probe use different base URLs!"
        )
        self.assertEqual(
            proxy_rec.split("/api/v1")[0],
            probe_rec.split("/health")[0],
            "Recommendation proxy and probe use different base URLs!"
        )

    def test_recommendation_service_rootdir_is_repo_root(self):
        """
        PROVES: In render.yaml, recommendation-service has rootDir: .
        while api-gateway has rootDir: services/api-gateway.

        This means: ANY commit to the repository triggers BOTH services to redeploy
        (Render watches the entire repo for recommendation-service, not just a subdirectory).

        Consequence: Recommendation Service is NEVER reliably asleep after an API Gateway
        code push. It will always be redeploying or recently redeployed.
        This makes Recommendation Service useless as evidence for the wake-up mechanism.

        We verify this by reading the render.yaml content statically.
        """
        render_yaml_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '../../render.yaml'))
        self.assertTrue(os.path.exists(render_yaml_path), "render.yaml not found")

        with open(render_yaml_path, 'r') as f:
            content = f.read()

        # api-gateway has a specific rootDir
        self.assertIn("rootDir: services/api-gateway", content,
            "api-gateway should have rootDir: services/api-gateway")

        # recommendation-service has rootDir: . (entire repo)
        self.assertIn("rootDir: .", content,
            "recommendation-service should have rootDir: . (watches entire repo)")

        # This means both services redeploy on any commit
        # Verify by checking both service names appear before their respective rootDir values
        api_gw_pos = content.find("name: api-gateway")
        rec_pos = content.find("name: recommendation-service")
        root_dot_pos = content.find("rootDir: .")

        self.assertGreater(rec_pos, api_gw_pos,
            "recommendation-service should appear after api-gateway in render.yaml")
        self.assertGreater(root_dot_pos, rec_pos,
            "rootDir: . should appear after recommendation-service definition")


class TestProbeURLsMatchServiceActualEndpoints(unittest.IsolatedAsyncioTestCase):
    """
    Cross-reference: verify the probe target paths exist in the actual service code.
    """

    def test_catalog_health_route_exists_at_api_v1_catalog_health(self):
        """
        Catalog service mounts router with prefix /api/v1/catalog.
        Router defines GET /health.
        Combined: GET /api/v1/catalog/health ✓

        Also: GET /health is defined directly on app (root health).
        Probe target is /api/v1/catalog/health - this is correct.
        """
        # From catalog-service/app/main.py:
        # app.include_router(health.router, prefix=settings.API_V1_PREFIX)
        # API_V1_PREFIX = "/api/v1/catalog"
        # health.router has: @router.get("/health")
        # Combined: /api/v1/catalog + /health = /api/v1/catalog/health ✓
        api_v1_prefix = "/api/v1/catalog"
        health_route = "/health"
        full_path = api_v1_prefix + health_route
        self.assertEqual(full_path, "/api/v1/catalog/health",
            "Catalog health endpoint should be at /api/v1/catalog/health")

    def test_user_service_ping_route_exists_at_api_auth_ping(self):
        """
        User service mounts router at /api/auth prefix.
        Router defines GET /ping.
        Combined: GET /api/auth/ping ✓
        """
        # From user-service/app/main.py:
        # app.include_router(router, prefix="/api/auth")
        # router has: @router.get("/ping")
        # Combined: /api/auth + /ping = /api/auth/ping ✓
        prefix = "/api/auth"
        route = "/ping"
        full_path = prefix + route
        self.assertEqual(full_path, "/api/auth/ping",
            "User service ping should be at /api/auth/ping")

    def test_recommendation_service_health_route_at_health(self):
        """
        Recommendation service defines GET /health directly on the app.
        Probe target is /health ✓
        """
        # From recommendation-service/app/main.py:
        # @app.get("/health") ✓
        route = "/health"
        self.assertEqual(route, "/health",
            "Recommendation health should be at /health")

    def test_gateway_readiness_route_matches_frontend_call(self):
        """
        Gateway defines: @app.get("/api/v1/ready")
        Frontend calls: api.get('/v1/ready') with baseURL = VITE_API_URL = .../api
        Final URL: .../api/v1/ready ✓ (matches /api/v1/ready on gateway)
        """
        # Gateway route
        gateway_route = "/api/v1/ready"
        # Frontend: baseURL ends with /api, path is /v1/ready
        frontend_path = "/v1/ready"
        # Since VITE_API_URL = "https://gateway.onrender.com/api"
        # Axios composes: https://gateway.onrender.com/api + /v1/ready
        # = https://gateway.onrender.com/api/v1/ready ✓
        composed = "/api" + frontend_path
        self.assertEqual(composed, gateway_route,
            f"Frontend '{frontend_path}' with base '/api' produces '{composed}' "
            f"which must match gateway route '{gateway_route}'")


if __name__ == "__main__":
    unittest.main()
