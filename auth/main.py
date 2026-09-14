import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, Header, HTTPException
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlmodel import Field, Session, SQLModel, create_engine, select

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./auth.db")
SECRET = os.getenv("JWT_SECRET", "devsecret")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
INTERNAL_KEY = os.getenv("INTERNAL_KEY", "")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
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




class User(SQLModel, table=True):
    __tablename__ = "users"
    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True)
    hashed_password: str


class RevokedToken(SQLModel, table=True):
    __tablename__ = "revoked_tokens"
    jti: str = Field(primary_key=True)
    username: str
    expires_at: datetime


class UserCreate(BaseModel):
    username: str
    password: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    SQLModel.metadata.create_all(engine)
    yield


app = FastAPI(title="Auth Service", lifespan=lifespan)


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


def create_access_token(username: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, SECRET, algorithm=ALGORITHM)


def decode(authorization: str) -> dict:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Invalid authorization header")
    try:
        return jwt.decode(authorization.split(" ", 1)[1], SECRET, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(401, "Invalid or expired token")


@app.post("/register", dependencies=[Depends(require_internal)])
def register(user: UserCreate, session: Session = Depends(get_session)):
    if not user.username.strip() or len(user.password) < 6:
        raise HTTPException(400, "username required, password min 6 characters")
    exists = session.exec(select(User).where(User.username == user.username)).first()
    if exists:
        raise HTTPException(400, "username taken")
    u = User(username=user.username, hashed_password=pwd_context.hash(user.password[:72]))
    session.add(u)
    session.commit()
    session.refresh(u)
    return {"id": u.id, "username": u.username}


@app.post("/token", dependencies=[Depends(require_internal)])
def login(form: UserCreate, session: Session = Depends(get_session)):
    user = session.exec(select(User).where(User.username == form.username)).first()
    if not user or not pwd_context.verify(form.password[:72], user.hashed_password):
        raise HTTPException(401, "invalid credentials")
    return {"access_token": create_access_token(user.username), "token_type": "bearer"}


@app.post("/verify", dependencies=[Depends(require_internal)])
def verify(authorization: str = Header(...), session: Session = Depends(get_session)):
    payload = decode(authorization)
    if session.get(RevokedToken, payload["jti"]):
        raise HTTPException(401, "Token revoked")
    return {"username": payload["sub"], "jti": payload["jti"]}


@app.post("/logout", dependencies=[Depends(require_internal)])
def logout(authorization: str = Header(...), session: Session = Depends(get_session)):
    payload = decode(authorization)
    if not session.get(RevokedToken, payload["jti"]):
        session.add(RevokedToken(
            jti=payload["jti"],
            username=payload["sub"],
            expires_at=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
        ))
        session.commit()
    return {"msg": "Logged out successfully"}


@app.get("/health")
def health():
    return {"status": "ok", "service": "auth"}
