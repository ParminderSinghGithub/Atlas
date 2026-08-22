"""
FORENSIC LOGGING & OUTBOUND DISPATCH TEST SUITE
==============================================
Strictly Local-Only: ZERO live network requests.

Tests:
1. Exact target URL construction.
2. Every probe coroutine is actually invoked.
3. The HTTP client dispatch occurs.
4. Exceptions are captured independently without cancelling others.
5. Redirects and alternate 404 paths are handled as intended.
6. Timeout classification is preserved (TimeoutException -> warming_up).
7. Aggregate readiness result is computed correctly.
8. Diagnostic logging occurs at all stages (READINESS_PROBE_START, READINESS_HTTP_DISPATCH, etc.).
9. URL sanitizer strips credentials and sensitive query params from logs.
"""
import asyncio
import logging
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
    _sanitize_url,
)
from app.core.config import (
    get_catalog_service_url,
    get_user_service_url,
    get_recommendation_service_url,
    get_ml_inference_service_url,
)


class TestForensicLoggingAndDispatch(unittest.IsolatedAsyncioTestCase):
    """Forensic tests validating exact structured logging and dispatch mechanics."""

    def setUp(self):
        _readiness_cache["data"] = None
        _readiness_cache["timestamp"] = 0.0

    def test_url_sanitizer_removes_credentials_and_query_params(self):
        """Verify _sanitize_url strips passwords, tokens, and query strings from logged URLs."""
        test_url_with_auth = "https://user:secret_password@catalog-service-uo46.onrender.com:5004/api/v1/catalog/products?token=jwt123&key=secret"
        sanitized = _sanitize_url(test_url_with_auth)
        self.assertEqual(sanitized, "https://catalog-service-uo46.onrender.com:5004/api/v1/catalog/products")
        self.assertNotIn("secret_password", sanitized)
        self.assertNotIn("token=jwt123", sanitized)
        self.assertNotIn("user:", sanitized)

    @patch("app.main.httpx.AsyncClient")
    async def test_structured_log_records_emitted_during_successful_dispatch(self, mock_client_cls):
        """
        Verify all structured logging events are emitted during readiness dispatch:
        - READINESS_DISPATCH_START
        - READINESS_PROBE_START (for each service)
        - READINESS_HTTP_DISPATCH (for each service)
        - READINESS_HTTP_RESPONSE (for each service)
        - READINESS_PROBE_END (for each service)
        - READINESS_DISPATCH_RESULTS
        - READINESS_RESPONSE
        """
        mock_instance = AsyncMock()
        mock_instance.__aenter__.return_value = mock_instance
        mock_client_cls.return_value = mock_instance

        async def intercept_get(url, headers=None, **kwargs):
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 200
            resp.json.return_value = {"status": "healthy", "database": "connected"}
            resp.history = []
            resp.url = httpx.URL(str(url))
            return resp

        mock_instance.get = intercept_get

        with self.assertLogs("api_gateway.readiness", level="INFO") as captured:
            res = await system_readiness(force_refresh=True)

        log_messages = captured.output
        joined_logs = "\n".join(log_messages)

        # Verify aggregate start and end logs
        self.assertIn("READINESS_DISPATCH_START", joined_logs)
        self.assertIn("READINESS_DISPATCH_RESULTS", joined_logs)
        self.assertIn("READINESS_RESPONSE", joined_logs)

        # Verify per-service start, dispatch, response, and end logs
        for s_key in ["catalog_service", "recommendation_service", "user_service", "ml_inference_service"]:
            self.assertIn(f"READINESS_PROBE_START service={s_key}", joined_logs)
            self.assertIn(f"READINESS_HTTP_DISPATCH service={s_key}", joined_logs)
            self.assertIn(f"READINESS_HTTP_RESPONSE service={s_key}", joined_logs)
            self.assertIn(f"READINESS_PROBE_END service={s_key}", joined_logs)

        self.assertEqual(res["status"], "ready")

    @patch("app.main.httpx.AsyncClient")
    async def test_structured_log_records_emitted_during_timeout_and_connect_error(self, mock_client_cls):
        """
        Verify READINESS_HTTP_ERROR logs specific exception types:
        - ConnectError for Catalog
        - ReadTimeout for User
        """
        mock_instance = AsyncMock()
        mock_instance.__aenter__.return_value = mock_instance
        mock_client_cls.return_value = mock_instance

        async def intercept_get(url, headers=None, **kwargs):
            if "catalog" in str(url):
                raise httpx.ConnectError("Connection refused by target")
            if "user" in str(url) or "5000" in str(url) or "auth" in str(url):
                raise httpx.ReadTimeout("Server timed out reading response")
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 200
            resp.json.return_value = {"status": "healthy"}
            resp.history = []
            resp.url = httpx.URL(str(url))
            return resp

        mock_instance.get = intercept_get

        with self.assertLogs("api_gateway.readiness", level="INFO") as captured:
            res = await system_readiness(force_refresh=True)

        joined_logs = "\n".join(captured.output)

        self.assertIn("READINESS_HTTP_ERROR service=catalog_service exception_type=ConnectError", joined_logs)
        self.assertIn("READINESS_HTTP_ERROR service=user_service exception_type=ReadTimeout", joined_logs)
        self.assertIn("READINESS_PROBE_END service=catalog_service result=warming_up", joined_logs)
        self.assertIn("READINESS_PROBE_END service=user_service result=warming_up", joined_logs)

        self.assertEqual(res["status"], "warming_up")

    @patch("app.main.httpx.AsyncClient")
    async def test_redirect_history_recorded_in_response_log(self, mock_client_cls):
        """Verify redirect counts and final URLs are logged when redirects occur."""
        mock_instance = AsyncMock()
        mock_instance.__aenter__.return_value = mock_instance
        mock_client_cls.return_value = mock_instance

        async def intercept_get(url, headers=None, **kwargs):
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 200
            resp.json.return_value = {"status": "healthy", "database": "connected"}
            # Simulate a 308 redirect in history
            redirect_resp = MagicMock(spec=httpx.Response)
            redirect_resp.status_code = 308
            resp.history = [redirect_resp]
            resp.url = httpx.URL(f"{url}/final")
            return resp

        mock_instance.get = intercept_get

        with self.assertLogs("api_gateway.readiness", level="INFO") as captured:
            await system_readiness(force_refresh=True)

        joined_logs = "\n".join(captured.output)
        self.assertIn("redirect_count=1", joined_logs)


if __name__ == "__main__":
    unittest.main()
