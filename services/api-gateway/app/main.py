from fastapi import FastAPI
import httpx

app = FastAPI()

USER_SERVICE_URL = "http://user-service:5000"
PRODUCT_SERVICE_URL = "http://product-service:5000"

@app.get("/ping")
async def root():
    return {"message": "API Gateway alive"}

@app.get("/users/ping")
async def user_ping():
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{USER_SERVICE_URL}/api/auth/ping")
        return r.json()

@app.get("/products/ping")
async def product_ping():
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{PRODUCT_SERVICE_URL}/api/products/ping")
        return r.json()
