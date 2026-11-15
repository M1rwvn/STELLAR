import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.database import Base, SessionLocal, engine
from app.routers import alerts, astronauts, auth, dashboard, health_data, system
from app.seed import seed
from app.services.comm_link import comm_link

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)-5s %(name)s | %(message)s")
log = logging.getLogger("stellar")

DESCRIPTION = """
**STELLAR** backend - Digital Twin health monitoring for astronauts.

Flow of `POST /health-data`:
`reading -> get_baseline (AI 1) -> build_health_vector (AI 3) -> predict_risk (AI 2) -> store -> alert`

Risk levels: **Normal** 0-25 · **Attention** 25-50 · **High Risk** 50-75 · **Emergency** 75-100

How to try it: `POST /login` (e.g. `ground` / the seed password), copy `access_token`,
click **Authorize** and paste it.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    # No-op when Alembic already created the tables (Docker); creates them for local SQLite runs
    Base.metadata.create_all(engine)
    if settings.seed_on_startup:
        with SessionLocal() as db:
            seed(db)
    comm_link.delay = settings.comm_delay_seconds
    if settings.comm_link_enabled:
        comm_link.start()
    log.info("STELLAR backend ready (db=%s)", engine.url.render_as_string(hide_password=True))
    yield
    comm_link.stop()


settings = get_settings()
app = FastAPI(title=settings.app_name, version="1.0.0", description=DESCRIPTION,
              lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials="*" not in settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def timing_and_headers(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    response.headers["X-Process-Time-ms"] = f"{elapsed_ms:.1f}"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    if request.url.path not in ("/health",):
        log.info("%s %s -> %s (%.0f ms)", request.method, request.url.path,
                 response.status_code, elapsed_ms)
    return response


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


app.include_router(system.router)
app.include_router(auth.router)
app.include_router(health_data.router)
app.include_router(astronauts.router)
app.include_router(alerts.router)
app.include_router(dashboard.router)
