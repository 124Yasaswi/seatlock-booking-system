"""SeatLock API.

Run locally:
    python run.py            (Windows or Linux)
    uvicorn app.main:app     (Linux)
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import db
from app.config import settings
from app.realtime import hub
from app.routers import admin, auth, booking
from app.services.booking import BookingError, sweep_expired

log = logging.getLogger("seatlock")


async def sweeper_loop():
    """Background task: every few seconds, free the seats of expired holds."""
    while True:
        await asyncio.sleep(settings.sweep_seconds)
        try:
            async with db.pool.connection() as conn:
                await hub.publish(await sweep_expired(conn))
        except Exception:
            log.exception("sweeper failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.open_pool()
    task = asyncio.create_task(sweeper_loop()) if settings.run_sweeper else None
    yield
    if task:
        task.cancel()
    await db.close_pool()


app = FastAPI(title="SeatLock", version="1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins.split(","),
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(auth.router)
app.include_router(booking.router)
app.include_router(admin.router)


@app.exception_handler(BookingError)
async def booking_error(request: Request, exc: BookingError):
    return JSONResponse({"detail": exc.message, "code": exc.code, **exc.extra}, status_code=exc.status)


@app.get("/api/health")
async def health():
    return {"ok": True}


# In production the built React app is served by the same server.
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        return FileResponse(DIST / "index.html")
