from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import httpx

app = FastAPI()

# Add CORS middleware to allow frontend requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins (can restrict to specific origins in production)
    allow_credentials=False,  # Must be False when allow_origins is ["*"]
    allow_methods=["*"],  # Allow all HTTP methods
    allow_headers=["*"],  # Allow all headers
)

USER_SERVICE_URL = "http://user-service:5000"
PRODUCT_SERVICE_URL = "http://product-service:5000"
EVENT_SERVICE_URL = "http://event-service:5000"
CATALOG_SERVICE_URL = "http://catalog-service:5004"
RECOMMENDATION_SERVICE_URL = "http://recommendation-service:5005"

@app.get("/ping")
async def root():
    return {"message": "API Gateway alive"}

# ==================== USER SERVICE ROUTES ====================
@app.api_route("/api/auth/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy_auth(path: str, request: Request):
    """Proxy all /api/auth/* requests to user-service"""
    async with httpx.AsyncClient() as client:
        url = f"{USER_SERVICE_URL}/api/auth/{path}"
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

# ==================== PRODUCT SERVICE ROUTES ====================
@app.api_route("/api/products/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy_products_with_path(path: str, request: Request):
    """Proxy all /api/products/* requests to product-service"""
    async with httpx.AsyncClient() as client:
        url = f"{PRODUCT_SERVICE_URL}/api/products/{path}"
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

@app.api_route("/api/products", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy_products(request: Request):
    """Proxy /api/products (without path) to product-service"""
    async with httpx.AsyncClient() as client:
        url = f"{PRODUCT_SERVICE_URL}/api/products"
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
@app.api_route("/api/v1/catalog/{path:path}", methods=["GET", "OPTIONS"])
async def proxy_catalog(path: str, request: Request):
    """Proxy all /api/v1/catalog/* requests to catalog-service (read-only)"""
    async with httpx.AsyncClient() as client:
        url = f"{CATALOG_SERVICE_URL}/api/v1/catalog/{path}"
        headers = dict(request.headers)
        headers.pop("host", None)
        
        # Forward query parameters
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
@app.api_route("/api/v1/recommendations", methods=["GET", "OPTIONS"])
async def proxy_recommendations(request: Request):
    """Proxy /api/v1/recommendations to recommendation-service"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        url = f"{RECOMMENDATION_SERVICE_URL}/api/v1/recommendations"
        headers = dict(request.headers)
        headers.pop("host", None)
        
        # Forward query parameters
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

# ==================== EVENT SERVICE ROUTES ====================
@app.api_route("/events/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy_events_with_path(path: str, request: Request):
    """Proxy all /events/* requests to event-service"""
    async with httpx.AsyncClient() as client:
        url = f"{EVENT_SERVICE_URL}/events/{path}"
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

@app.api_route("/events", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy_events(request: Request):
    """Proxy /events (without path) to event-service"""
    async with httpx.AsyncClient() as client:
        url = f"{EVENT_SERVICE_URL}/events"
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
