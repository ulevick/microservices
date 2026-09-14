import asyncio
import os
import time
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import Body, Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

AUTH_URL = os.getenv("AUTH_URL", "http://127.0.0.1:8001")
CATALOG_URL = os.getenv("CATALOG_URL", "http://127.0.0.1:8002")
ORDER_URL = os.getenv("ORDER_URL", "http://127.0.0.1:8003")
INTERNAL_KEY = os.getenv("INTERNAL_KEY", "")
TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "5"))
TOKEN_CACHE_TTL = float(os.getenv("TOKEN_CACHE_TTL", "30"))

token_cache: dict[str, tuple[str, float]] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = httpx.AsyncClient(timeout=TIMEOUT)
    yield
    await app.state.http.aclose()


app = FastAPI(title="API Gateway", lifespan=lifespan)


@app.middleware("http")
async def trace_headers(request, call_next):
    start = time.perf_counter()
    request.state.rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.rid
    response.headers["X-Response-Time-ms"] = f"{(time.perf_counter() - start) * 1000:.1f}"
    return response


def internal_headers(request: Request, user: str | None = None) -> dict:
    headers = {"X-Internal-Key": INTERNAL_KEY, "X-Request-ID": request.state.rid}
    if user:
        headers["X-User"] = user
    return headers


async def call(request: Request, method: str, url: str, **kwargs) -> JSONResponse:
    try:
        r = await request.app.state.http.request(method, url, **kwargs)
    except httpx.RequestError:
        raise HTTPException(503, "service unavailable")
    try:
        body = r.json()
    except ValueError:
        raise HTTPException(502, "unexpected downstream response")
    return JSONResponse(status_code=r.status_code, content=body)


def bearer(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid token")
    return auth


async def current_user(request: Request) -> str:
    auth = bearer(request)
    now = time.time()
    cached = token_cache.get(auth)
    if cached and cached[1] > now:
        return cached[0]
    try:
        r = await request.app.state.http.post(
            f"{AUTH_URL}/verify",
            headers={**internal_headers(request), "Authorization": auth},
        )
    except httpx.RequestError:
        raise HTTPException(503, "auth service unavailable")
    if r.status_code == 401:
        raise HTTPException(401, r.json().get("detail", "Invalid token"))
    if r.status_code != 200:
        raise HTTPException(503, "auth service unavailable")
    username = r.json()["username"]
    if TOKEN_CACHE_TTL > 0:
        token_cache[auth] = (username, now + TOKEN_CACHE_TTL)
    return username


@app.post("/auth/register")
async def register(request: Request, payload: dict = Body(...)):
    return await call(request, "POST", f"{AUTH_URL}/register", json=payload,
                      headers=internal_headers(request))


@app.post("/auth/token")
async def login(request: Request, payload: dict = Body(...)):
    return await call(request, "POST", f"{AUTH_URL}/token", json=payload,
                      headers=internal_headers(request))


@app.post("/auth/logout")
async def logout(request: Request):
    auth = bearer(request)
    response = await call(request, "POST", f"{AUTH_URL}/logout",
                          headers={**internal_headers(request), "Authorization": auth})
    token_cache.pop(auth, None)
    return response


@app.post("/catalog/products")
async def create_product(request: Request, payload: dict = Body(...),
                         user: str = Depends(current_user)):
    return await call(request, "POST", f"{CATALOG_URL}/products", json=payload,
                      headers=internal_headers(request, user))


@app.get("/catalog/products")
async def list_products(request: Request, user: str = Depends(current_user)):
    return await call(request, "GET", f"{CATALOG_URL}/products",
                      headers=internal_headers(request, user))


@app.get("/catalog/products/{product_id}")
async def get_product(product_id: int, request: Request, user: str = Depends(current_user)):
    return await call(request, "GET", f"{CATALOG_URL}/products/{product_id}",
                      headers=internal_headers(request, user))


@app.post("/orders")
async def create_order(request: Request, payload: dict = Body(...),
                       user: str = Depends(current_user)):
    return await call(request, "POST", f"{ORDER_URL}/orders", json=payload,
                      headers=internal_headers(request, user))


@app.get("/orders")
async def list_orders(request: Request, user: str = Depends(current_user)):
    return await call(request, "GET", f"{ORDER_URL}/orders",
                      headers=internal_headers(request, user))


@app.get("/health")
async def health(request: Request):
    async def probe(name: str, url: str):
        try:
            r = await request.app.state.http.get(f"{url}/health", timeout=2.0)
            return name, "ok" if r.status_code == 200 else f"http {r.status_code}"
        except httpx.RequestError:
            return name, "unreachable"

    services = dict(await asyncio.gather(
        probe("auth", AUTH_URL), probe("catalog", CATALOG_URL), probe("order", ORDER_URL)
    ))
    degraded = [n for n, s in services.items() if s != "ok"]
    return JSONResponse(
        status_code=503 if degraded else 200,
        content={"status": "degraded" if degraded else "ok", "services": services},
    )
