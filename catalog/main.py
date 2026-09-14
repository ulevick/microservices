import os
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field as PField
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlmodel import Field, Session, SQLModel, create_engine, select

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./catalog.db")
INTERNAL_KEY = os.getenv("INTERNAL_KEY", "")

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




class Product(SQLModel, table=True):
    __tablename__ = "products"
    id: int | None = Field(default=None, primary_key=True)
    name: str
    price_cents: int


class ProductCreate(BaseModel):
    name: str = PField(min_length=1, max_length=200)
    price_cents: int = PField(ge=0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    SQLModel.metadata.create_all(engine)
    yield


app = FastAPI(title="Catalog Service", lifespan=lifespan)


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


@app.post("/products", dependencies=[Depends(require_internal)])
def create_product(p: ProductCreate, session: Session = Depends(get_session)):
    prod = Product(name=p.name, price_cents=p.price_cents)
    session.add(prod)
    session.commit()
    session.refresh(prod)
    return prod


@app.get("/products", dependencies=[Depends(require_internal)])
def list_products(session: Session = Depends(get_session)):
    return session.exec(select(Product).order_by(Product.id)).all()


@app.get("/products/{product_id}", dependencies=[Depends(require_internal)])
def get_product(product_id: int, session: Session = Depends(get_session)):
    prod = session.get(Product, product_id)
    if not prod:
        raise HTTPException(404, "not found")
    return prod


@app.get("/health")
def health():
    return {"status": "ok", "service": "catalog"}
