import os
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field as PField
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlmodel import Field, Session, SQLModel, create_engine, select

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./orders.db")
CATALOG_URL = os.getenv("CATALOG_URL", "http://127.0.0.1:8002")
INTERNAL_KEY = os.getenv("INTERNAL_KEY", "")
TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "3"))

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)

if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def sqlite_pragmas(conn, _):
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")


def init_db(retries: int = 6) -> None:
    for attempt in range(retries):
        try:
            init_db()
            return
        except OperationalError:
            if attempt == retries - 1:
                raise
            time.sleep(0.4 * (attempt + 1))




class Order(SQLModel, table=True):
    __tablename__ = "orders"
    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(index=True)
    product_id: int
    product_name: str
    price_cents_snapshot: int
    quantity: int


class OrderCreate(BaseModel):
    product_id: int = PField(gt=0)
    quantity: int = PField(gt=0, le=1000)


@asynccontextmanager
async def lifespan(app: FastAPI):
    SQLModel.metadata.create_all(engine)
    app.state.http = httpx.AsyncClient(timeout=TIMEOUT)
    yield
    await app.state.http.aclose()


app = FastAPI(title="Order Service", lifespan=lifespan)


@app.middleware("http")
async def trace_headers(request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Response-Time-ms"] = f"{(time.perf_counter() - start) * 1000:.1f}"
    rid = request.headers.get("X-Request-ID")
    if rid:
        response.headers["X-Request-ID"] = rid
    return response


def get_session():
    with Session(engine) as s:
        yield s


def require_internal(x_internal_key: str = Header(default="")):
    if INTERNAL_KEY and x_internal_key != INTERNAL_KEY:
        raise HTTPException(403, "internal endpoint")


def current_user(x_user: str = Header(...)):
    return x_user


async def fetch_product(request: Request, product_id: int) -> dict:
    headers = {"X-Internal-Key": INTERNAL_KEY}
    rid = request.headers.get("X-Request-ID")
    if rid:
        headers["X-Request-ID"] = rid
    try:
        r = await request.app.state.http.get(f"{CATALOG_URL}/products/{product_id}", headers=headers)
    except httpx.RequestError:
        raise HTTPException(503, "catalog service unavailable")
    if r.status_code == 404:
        raise HTTPException(400, "product not found")
    if r.status_code >= 500:
        raise HTTPException(503, "catalog service unavailable")
    if r.status_code != 200:
        raise HTTPException(502, "unexpected catalog response")
    return r.json()


@app.post("/orders", dependencies=[Depends(require_internal)])
async def create_order(
    o: OrderCreate,
    request: Request,
    username: str = Depends(current_user),
    session: Session = Depends(get_session),
):
    product = await fetch_product(request, o.product_id)
    order = Order(
        username=username,
        product_id=product["id"],
        product_name=product["name"],
        price_cents_snapshot=product["price_cents"],
        quantity=o.quantity,
    )
    session.add(order)
    session.commit()
    session.refresh(order)
    return {**order.model_dump(), "total_cents": order.price_cents_snapshot * order.quantity}


@app.get("/orders", dependencies=[Depends(require_internal)])
def list_orders(username: str = Depends(current_user), session: Session = Depends(get_session)):
    rows = session.exec(select(Order).where(Order.username == username).order_by(Order.id)).all()
    return [{**o.model_dump(), "total_cents": o.price_cents_snapshot * o.quantity} for o in rows]


@app.get("/health")
def health():
    return {"status": "ok", "service": "order"}
