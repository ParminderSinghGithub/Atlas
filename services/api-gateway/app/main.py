"""
Atlas API Gateway - Main Application

Unified gateway orchestrating requests across:
- Catalog Service (Products, Categories, Event Ingestion)
- Recommendation Service (Hybrid Recommendations, Session Tracking)
- User Service (Authentication, Identity, Password Recovery)
- External ML Inference Service (OCI OCI-hosted High-throughput Models)
"""
import asyncio
import time
import logging
from urllib.parse import urlparse
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import httpx

# Configure structured readiness logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
)
logger = logging.getLogger("api_gateway.readiness")

from app.core import settings
from app.core.config import (
    get_recommendation_service_url,
    get_recommendation_service_url_source,
    get_catalog_service_url,
    get_user_service_url,
    get_ml_inference_service_url,
    validate_service_url,
)

tags_metadata = [
    {
        "name": "Health & Readiness",
        "description": "System liveness, readiness, and coordinated cold-start warm-up probes.",
    },
    {
        "name": "Recommendations & Session",
        "description": "Recommendation queries and real-time session intent tracking.",
    },
    {
        "name": "Catalog",
        "description": "Product catalog queries and category navigation.",
    },
    {
        "name": "Authentication",
        "description": "User registration, login, profile, and password recovery.",
    },
    {
        "name": "Events",
        "description": "Client interaction event ingestion (views, clicks, purchases).",
    },
]

app = FastAPI(
    title="Atlas API Gateway",
    description="Unified API Gateway and request orchestrator for the Atlas e-commerce and recommendation platform.",
    version="2.0.0",
    openapi_tags=tags_metadata,
    docs_url="/docs",
    redoc_url="/redoc",
)

# In-memory readiness cache to prevent request flooding
_readiness_cache: Dict[str, Any] = {
    "data": None,
    "timestamp": 0.0,
}
_readiness_lock = asyncio.Lock()


@app.on_event("startup")
async def startup_diagnostics():
    """Log and validate downstream service URL configuration."""
    rec_url = get_recommendation_service_url()
    cat_url = get_catalog_service_url()
    user_url = get_user_service_url()
    ml_url = get_ml_inference_service_url()
    url_source = get_recommendation_service_url_source()
    print(f"Atlas API Gateway 2.0 starting up...")
    print(f"Recommendation service URL: {rec_url} ({url_source})")
    print(f"Catalog service URL: {cat_url}")
    print(f"User service URL: {user_url}")
    print(f"ML Inference service URL: {ml_url}")
    validate_service_url(rec_url, "RECOMMENDATION_SERVICE_URL")
    validate_service_url(cat_url, "CATALOG_SERVICE_URL")
    validate_service_url(user_url, "USER_SERVICE_URL")
    validate_service_url(ml_url, "ML_INFERENCE_SERVICE_URL")


# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/ping", tags=["Health & Readiness"], summary="Gateway Liveness Ping")
async def root():
    """Fast liveness check for API Gateway."""
    return {"message": "Atlas API Gateway alive", "service": "api-gateway", "status": "ok"}


@app.get("/health", tags=["Health & Readiness"], summary="Gateway Health Check")
async def health():
    """Standard health check endpoint."""
    return {
        "status": "healthy",
        "service": "api-gateway",
        "version": "2.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _sanitize_url(url: str) -> str:
    """Sanitize URL to ensure credentials/query parameters are stripped for safe diagnostic logging."""
    try:
        parsed = urlparse(url)
        netloc = parsed.hostname or ""
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"
        return f"{parsed.scheme}://{netloc}{parsed.path}"
    except Exception:
        return url


async def _probe_single_service(
    client: httpx.AsyncClient,
    service_key: str,
    name: str,
    url: str,
    is_critical: bool = True,
    custom_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Probe a single downstream service and verify actual readiness with structured diagnostic logging."""
    t0 = time.time()
    sanitized_url = _sanitize_url(url)
    iso_now = datetime.now(timezone.utc).isoformat()
    logger.info(
        "READINESS_PROBE_START service=%s target=%s timestamp=%s",
        service_key, sanitized_url, iso_now
    )

    headers = {
        "Accept": "application/json",
        "User-Agent": (custom_headers.get("user-agent") if custom_headers and "user-agent" in custom_headers else "Atlas-API-Gateway/2.0"),
    }
    if custom_headers:
        for hk in ["accept-language", "sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform"]:
            if hk in custom_headers:
                headers[hk] = custom_headers[hk]

    timeout_s = getattr(client.timeout, "read", settings.PROBE_TIMEOUT_SECONDS)
    follow_redirects = getattr(client, "follow_redirects", True)

    logger.info(
        "READINESS_HTTP_DISPATCH service=%s method=GET target=%s timeout=%s follow_redirects=%s",
        service_key, sanitized_url, timeout_s, follow_redirects
    )

    try:
        resp = await client.get(url, headers=headers)
        elapsed_ms = round((time.time() - t0) * 1000, 2)
        redirect_count = len(resp.history) if isinstance(getattr(resp, "history", None), list) else 0
        final_url = sanitized_url
        raw_resp_url = getattr(resp, "url", None)
        if raw_resp_url is not None and not type(raw_resp_url).__name__.startswith("MagicMock"):
            final_url = _sanitize_url(str(raw_resp_url))

        logger.info(
            "READINESS_HTTP_RESPONSE service=%s status=%s elapsed_ms=%s final_url=%s redirect_count=%s",
            service_key, resp.status_code, elapsed_ms, final_url, redirect_count
        )

        if resp.status_code == 404:
            # Try alternate health path cleanly
            alt_url = None
            if "/api/v1/catalog/health" in url:
                alt_url = url.replace("/api/v1/catalog/health", "/health")
            elif "/health" in url:
                alt_url = url.replace("/health", "/api/v1/catalog/health")

            if alt_url and alt_url != url:
                sanitized_alt = _sanitize_url(alt_url)
                logger.info(
                    "READINESS_HTTP_DISPATCH service=%s method=GET target=%s (fallback_attempt)",
                    service_key, sanitized_alt
                )
                try:
                    resp = await client.get(alt_url, headers=headers)
                    elapsed_ms = round((time.time() - t0) * 1000, 2)
                    redirect_count = len(resp.history) if isinstance(getattr(resp, "history", None), list) else 0
                    final_url = sanitized_alt
                    raw_fb_url = getattr(resp, "url", None)
                    if raw_fb_url is not None and not type(raw_fb_url).__name__.startswith("MagicMock"):
                        final_url = _sanitize_url(str(raw_fb_url))
                    logger.info(
                        "READINESS_HTTP_RESPONSE service=%s status=%s elapsed_ms=%s final_url=%s redirect_count=%s (fallback)",
                        service_key, resp.status_code, elapsed_ms, final_url, redirect_count
                    )
                except Exception as fb_err:
                    logger.warning(
                        "READINESS_HTTP_ERROR service=%s fallback_exception_type=%s exception=%s",
                        service_key, type(fb_err).__name__, str(fb_err)
                    )

        if resp.status_code in (200, 204):
            # Inspect body to ensure database/dependencies are ready
            body = {}
            try:
                body = resp.json()
            except Exception:
                pass

            # If service reported unhealthy status or disconnected DB, mark warming_up
            if isinstance(body, dict):
                if body.get("status") == "unhealthy" or body.get("database") == "disconnected" or body.get("db") == "disconnected":
                    res = {
                        "name": name,
                        "status": "warming_up",
                        "latency_ms": elapsed_ms,
                        "critical": is_critical,
                        "status_code": resp.status_code,
                        "detail": "Database initializing",
                    }
                    logger.info(
                        "READINESS_PROBE_END service=%s result=warming_up elapsed_ms=%s detail='Database initializing'",
                        service_key, elapsed_ms
                    )
                    return res

            res = {
                "name": name,
                "status": "ready",
                "latency_ms": elapsed_ms,
                "critical": is_critical,
                "status_code": resp.status_code,
            }
            logger.info(
                "READINESS_PROBE_END service=%s result=ready elapsed_ms=%s status_code=%s",
                service_key, elapsed_ms, resp.status_code
            )
            return res
        else:
            # Extract key edge and rate-limiting headers for forensic observability
            diag_headers = {}
            raw_headers = getattr(resp, "headers", None)
            if raw_headers is not None and isinstance(raw_headers, (dict, httpx.Headers)):
                for k in ["server", "retry-after", "cf-ray", "x-render-origin-server", "content-type", "x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset"]:
                    if k in raw_headers:
                        diag_headers[k] = str(raw_headers[k])

            body_preview = ""
            raw_text = getattr(resp, "text", None)
            if isinstance(raw_text, str):
                body_preview = raw_text[:200].replace("\n", " ").strip()

            logger.warning(
                "READINESS_HTTP_NON_200 service=%s status=%s elapsed_ms=%s headers=%s body_preview='%s'",
                service_key, resp.status_code, elapsed_ms, diag_headers, body_preview
            )

            status_result = "warming_up" if resp.status_code in (429, 500, 502, 503, 504) else "degraded"
            res = {
                "name": name,
                "status": status_result,
                "latency_ms": elapsed_ms,
                "critical": is_critical,
                "status_code": resp.status_code,
                "error": f"HTTP {resp.status_code} ({'Rate limited / edge throttling' if resp.status_code == 429 else 'Upstream warming up'})",
            }
            if "retry-after" in diag_headers:
                res["retry_after"] = diag_headers["retry-after"]
            logger.info(
                "READINESS_PROBE_END service=%s result=%s elapsed_ms=%s status_code=%s",
                service_key, status_result, elapsed_ms, resp.status_code
            )
            return res

    except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout, httpx.TimeoutException) as e:
        elapsed_ms = round((time.time() - t0) * 1000, 2)
        exc_type = type(e).__name__
        logger.warning(
            "READINESS_HTTP_ERROR service=%s exception_type=%s exception=%s elapsed_ms=%s",
            service_key, exc_type, str(e), elapsed_ms
        )
        res = {
            "name": name,
            "status": "warming_up",
            "latency_ms": elapsed_ms,
            "critical": is_critical,
            "error": f"Container warming up ({exc_type})",
        }
        logger.info(
            "READINESS_PROBE_END service=%s result=warming_up elapsed_ms=%s error=%s",
            service_key, elapsed_ms, exc_type
        )
        return res

    except (httpx.ConnectError, httpx.RemoteProtocolError, httpx.NetworkError) as e:
        elapsed_ms = round((time.time() - t0) * 1000, 2)
        exc_type = type(e).__name__
        logger.warning(
            "READINESS_HTTP_ERROR service=%s exception_type=%s exception=%s elapsed_ms=%s",
            service_key, exc_type, str(e), elapsed_ms
        )
        res = {
            "name": name,
            "status": "warming_up",
            "latency_ms": elapsed_ms,
            "critical": is_critical,
            "error": f"Container warming up ({exc_type})",
        }
        logger.info(
            "READINESS_PROBE_END service=%s result=warming_up elapsed_ms=%s error=%s",
            service_key, elapsed_ms, exc_type
        )
        return res

    except httpx.HTTPStatusError as e:
        elapsed_ms = round((time.time() - t0) * 1000, 2)
        exc_type = type(e).__name__
        logger.warning(
            "READINESS_HTTP_ERROR service=%s exception_type=%s exception=%s elapsed_ms=%s",
            service_key, exc_type, str(e), elapsed_ms
        )
        res = {
            "name": name,
            "status": "degraded",
            "latency_ms": elapsed_ms,
            "critical": is_critical,
            "error": str(e),
        }
        logger.info(
            "READINESS_PROBE_END service=%s result=degraded elapsed_ms=%s",
            service_key, elapsed_ms
        )
        return res

    except httpx.TooManyRedirects as e:
        elapsed_ms = round((time.time() - t0) * 1000, 2)
        logger.warning(
            "READINESS_HTTP_ERROR service=%s exception_type=TooManyRedirects exception=%s elapsed_ms=%s",
            service_key, str(e), elapsed_ms
        )
        res = {
            "name": name,
            "status": "unavailable",
            "latency_ms": elapsed_ms,
            "critical": is_critical,
            "error": "Too many redirects",
        }
        logger.info(
            "READINESS_PROBE_END service=%s result=unavailable elapsed_ms=%s",
            service_key, elapsed_ms
        )
        return res

    except asyncio.CancelledError:
        elapsed_ms = round((time.time() - t0) * 1000, 2)
        logger.warning(
            "READINESS_HTTP_ERROR service=%s exception_type=CancelledError exception='Probe task cancelled' elapsed_ms=%s",
            service_key, elapsed_ms
        )
        raise

    except Exception as e:
        elapsed_ms = round((time.time() - t0) * 1000, 2)
        exc_type = type(e).__name__
        logger.error(
            "READINESS_HTTP_ERROR service=%s exception_type=%s exception=%s elapsed_ms=%s",
            service_key, exc_type, str(e), elapsed_ms
        )
        res = {
            "name": name,
            "status": "unavailable",
            "latency_ms": elapsed_ms,
            "critical": is_critical,
            "error": str(e),
        }
        logger.info(
            "READINESS_PROBE_END service=%s result=unavailable elapsed_ms=%s error=%s",
            service_key, elapsed_ms, exc_type
        )
        return res


@app.get("/api/v1/ready", tags=["Health & Readiness"], summary="Coordinated System Readiness & Warm-up")
@app.get("/ready", tags=["Health & Readiness"], summary="Coordinated System Readiness & Warm-up Alias")
async def system_readiness(request: Request = None, force_refresh: bool = False):
    """
    Coordinated readiness and warm-up probe for Atlas.
    
    Concurrently probes and warms all core microservices:
    - Catalog Service
    - Recommendation Service
    - User Service
    - ML Inference Service (OCI)
    
    Returns structured status indicating overall readiness:
    - 'ready': All core and optional dependencies are responsive.
    - 'warming_up': One or more critical services are waking from cold start.
    - 'degraded': Core services (Catalog, Recommendation, User) are ready, optional ML engine is waking.
    - 'unavailable': Critical dependencies unreachable.
    """
    now = time.time()
    if not force_refresh and _readiness_cache["data"] is not None:
        cache_age = now - _readiness_cache["timestamp"]
        is_cached_ready = _readiness_cache["data"].get("status") in ("ready", "degraded")
        max_cache_age = settings.READINESS_CACHE_TTL_SECONDS if is_cached_ready else 2.0
        if cache_age < max_cache_age:
            return _readiness_cache["data"]

    async with _readiness_lock:
        # Double check after lock
        if not force_refresh and _readiness_cache["data"] is not None:
            cache_age = time.time() - _readiness_cache["timestamp"]
            is_cached_ready = _readiness_cache["data"].get("status") in ("ready", "degraded")
            max_cache_age = settings.READINESS_CACHE_TTL_SECONDS if is_cached_ready else 2.0
            if cache_age < max_cache_age:
                return _readiness_cache["data"]

        t_dispatch_start = time.time()
        rec_url = get_recommendation_service_url()
        cat_url = get_catalog_service_url()
        user_url = get_user_service_url()
        ml_url = get_ml_inference_service_url()

        probes = [
            ("catalog_service", "Catalog Service", f"{cat_url}/api/v1/catalog/health", True),
            ("recommendation_service", "Recommendation Service", f"{rec_url}/health", True),
            ("user_service", "User Service", f"{user_url}/api/auth/ping", True),
            ("ml_inference_service", "ML Inference Engine", f"{ml_url}/health", False),
        ]

        targets_dict = {key: _sanitize_url(url) for key, name, url, critical in probes}
        logger.info("READINESS_DISPATCH_START targets=%s", targets_dict)

        client_headers = dict(request.headers) if request is not None and hasattr(request, "headers") else {}

        timeout = httpx.Timeout(settings.PROBE_TIMEOUT_SECONDS)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            tasks = [
                _probe_single_service(client, key, name, url, critical, custom_headers=client_headers)
                for key, name, url, critical in probes
            ]
            results_list = await asyncio.gather(*tasks, return_exceptions=True)

        services_dict = {
            "api_gateway": {
                "name": "API Gateway",
                "status": "ready",
                "latency_ms": 0.1,
                "critical": True,
            }
        }
        for probe_def, res in zip(probes, results_list):
            if isinstance(res, Exception):
                services_dict[probe_def[0]] = {
                    "name": probe_def[1],
                    "status": "warming_up",
                    "latency_ms": 0.0,
                    "critical": probe_def[3],
                    "error": str(res),
                }
            else:
                services_dict[probe_def[0]] = res

        # Compute overall status
        ready_count = sum(1 for s in services_dict.values() if s.get("status") == "ready")
        warming_count = sum(1 for s in services_dict.values() if s.get("status") == "warming_up")
        total_count = len(services_dict)

        critical_ready = all(
            s.get("status") == "ready"
            for s in services_dict.values()
            if s.get("critical", False)
        )
        critical_warming = any(
            s.get("status") == "warming_up"
            for s in services_dict.values()
            if s.get("critical", False)
        )

        if ready_count == total_count:
            overall_status = "ready"
        elif critical_ready:
            overall_status = "degraded"  # All critical services ready (Catalog, Recommendation, User)
        elif critical_warming:
            overall_status = "warming_up"
        else:
            overall_status = "unavailable"

        response_data = {
            "status": overall_status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "total": total_count,
                "ready": ready_count,
                "warming": warming_count,
                "unavailable": total_count - ready_count - warming_count,
            },
            "services": services_dict,
        }

        _readiness_cache["data"] = response_data
        _readiness_cache["timestamp"] = time.time()

        logger.info(
            "READINESS_DISPATCH_RESULTS catalog=%s user=%s recommendation=%s ml=%s",
            services_dict.get("catalog_service", {}).get("status"),
            services_dict.get("user_service", {}).get("status"),
            services_dict.get("recommendation_service", {}).get("status"),
            services_dict.get("ml_inference_service", {}).get("status"),
        )

        total_elapsed_ms = round((time.time() - t_dispatch_start) * 1000, 2)
        logger.info(
            "READINESS_RESPONSE status=%s overall_state=%s total_elapsed_ms=%s",
            overall_status, overall_status, total_elapsed_ms
        )

        return response_data


# ==================== USER SERVICE ROUTES ====================
@app.api_route("/api/auth/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"], tags=["Authentication"])
async def proxy_auth(path: str, request: Request):
    """Proxy all /api/auth/* requests to user-service."""
    async with httpx.AsyncClient(follow_redirects=True) as client:
        base_url = get_user_service_url()
        url = f"{base_url}/api/auth/{path}"
        headers = dict(request.headers)
        headers.pop("host", None)
        
        try:
            body = await request.body()
            response = await client.request(
                method=request.method,
                url=url,
                content=body,
                headers=headers,
            )
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers),
            )
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)


# ==================== CATALOG SERVICE ROUTES ====================
@app.api_route("/api/v1/catalog/{path:path}", methods=["GET", "OPTIONS"], tags=["Catalog"])
@app.api_route("/api/v1/products{path:path}", methods=["GET", "OPTIONS"], tags=["Catalog"])
@app.api_route("/api/v1/categories{path:path}", methods=["GET", "OPTIONS"], tags=["Catalog"])
async def proxy_catalog(request: Request, path: str = ""):
    """Proxy all catalog and taxonomy requests to catalog-service."""
    async with httpx.AsyncClient(follow_redirects=True) as client:
        base_url = get_catalog_service_url()
        req_path = request.url.path
        if req_path.startswith("/api/v1/catalog/"):
            sub = req_path[len("/api/v1/catalog/"):]
            url = f"{base_url.rstrip('/')}/api/v1/catalog/{sub}"
        elif req_path.startswith("/api/v1/products"):
            sub = req_path[len("/api/v1/products"):]
            url = f"{base_url.rstrip('/')}/api/v1/catalog/products{sub}"
        elif req_path.startswith("/api/v1/categories"):
            sub = req_path[len("/api/v1/categories"):]
            url = f"{base_url.rstrip('/')}/api/v1/catalog/categories{sub}"
        else:
            url = f"{base_url.rstrip('/')}/api/v1/catalog/{path}"

        headers = dict(request.headers)
        headers.pop("host", None)
        
        query_params = str(request.url.query)
        if query_params:
            url = f"{url}?{query_params}"
        
        try:
            response = await client.get(url, headers=headers)
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers),
            )
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)


# ==================== RECOMMENDATION SERVICE ROUTES ====================
@app.api_route("/api/v1/recommendations", methods=["GET", "OPTIONS"], tags=["Recommendations & Session"])
async def proxy_recommendations(request: Request):
    """Proxy /api/v1/recommendations to recommendation-service."""
    async with httpx.AsyncClient(timeout=settings.RECOMMENDATION_TIMEOUT_SECONDS, follow_redirects=True) as client:
        base_url = get_recommendation_service_url()
        url = f"{base_url}/api/v1/recommendations"
        headers = dict(request.headers)
        headers.pop("host", None)
        
        query_params = str(request.url.query)
        if query_params:
            url = f"{url}?{query_params}"
        
        try:
            response = await client.get(url, headers=headers)
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers),
            )
        except httpx.TimeoutException as e:
            return JSONResponse({"error": f"Recommendation request timed out ({settings.RECOMMENDATION_TIMEOUT_SECONDS}s)"}, status_code=504)
        except httpx.HTTPError as e:
            return JSONResponse({"error": str(e)}, status_code=502)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)


@app.api_route("/api/v1/session/track", methods=["POST", "OPTIONS"], tags=["Recommendations & Session"])
async def proxy_session_track(request: Request):
    """Proxy session tracking to recommendation-service."""
    async with httpx.AsyncClient(follow_redirects=True) as client:
        base_url = get_recommendation_service_url()
        url = f"{base_url}/api/v1/session/track"
        headers = dict(request.headers)
        headers.pop("host", None)
        
        try:
            body = await request.body()
            response = await client.request(
                method=request.method,
                url=url,
                content=body,
                headers=headers,
            )
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers),
            )
        except httpx.TimeoutException as e:
            return JSONResponse({"error": str(e)}, status_code=504)
        except httpx.HTTPError as e:
            return JSONResponse({"error": str(e)}, status_code=502)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)


# ==================== EVENT INGESTION ROUTES ====================
@app.api_route("/api/events/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"], tags=["Events"])
@app.api_route("/api/events", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"], tags=["Events"])
@app.api_route("/api/v1/events/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"], tags=["Events"])
@app.api_route("/api/v1/events", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"], tags=["Events"])
@app.api_route("/events/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"], tags=["Events"])
@app.api_route("/events", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"], tags=["Events"])
async def proxy_events(request: Request, path: str = ""):
    """Proxy all event ingestion requests to catalog-service."""
    async with httpx.AsyncClient(follow_redirects=True) as client:
        base_url = get_catalog_service_url()
        target_path = f"/events/{path}" if path else "/events"
        url = f"{base_url}{target_path}"
        headers = dict(request.headers)
        headers.pop("host", None)
        
        try:
            body = await request.body()
            response = await client.request(
                method=request.method,
                url=url,
                content=body,
                headers=headers,
            )
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers),
            )
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)
