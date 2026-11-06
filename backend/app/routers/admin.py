from fastapi import APIRouter, Depends

from app.db import get_conn
from app.schemas import ShowCreateIn
from app.security import admin_user
from app.services import analytics

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(admin_user)])


@router.get("/dashboard")
async def dashboard(conn=Depends(get_conn)):
    return await analytics.dashboard(conn)


@router.get("/venues")
async def venues(conn=Depends(get_conn)):
    return await (await conn.execute("SELECT * FROM venues ORDER BY id")).fetchall()


@router.get("/venues/{venue_id}/heatmap")
async def heatmap(venue_id: int, conn=Depends(get_conn)):
    return await analytics.seat_heatmap(conn, venue_id)


@router.post("/shows", status_code=201)
async def create_show(body: ShowCreateIn, conn=Depends(get_conn)):
    async with conn.transaction():
        show = await (await conn.execute("""
            INSERT INTO shows (venue_id, title, starts_at, regular_price_paise, premium_price_paise)
            VALUES (%s, %s, %s, %s, %s) RETURNING *""",
            (body.venue_id, body.title, body.starts_at, body.regular_price_paise, body.premium_price_paise))).fetchone()
        # one inventory row per physical seat, created in a single INSERT ... SELECT
        await conn.execute("INSERT INTO show_seats (show_id, seat_id) SELECT %s, id FROM seats WHERE venue_id = %s",
                           (show["id"], body.venue_id))
    return show
