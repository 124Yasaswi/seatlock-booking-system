from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.config import settings

MAX = settings.max_seats_per_booking


class RegisterIn(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=60)
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    # not EmailStr: login only looks the address up, and the demo accounts use
    # the reserved .test domain on purpose, which EmailStr refuses
    email: str = Field(min_length=3, max_length=254)
    password: str


class HoldIn(BaseModel):
    seat_ids: list[int] = Field(min_length=1, max_length=MAX)


class BestHoldIn(BaseModel):
    count: int = Field(ge=1, le=MAX)


class WaitlistIn(BaseModel):
    seats_wanted: int = Field(ge=1, le=MAX)


class ShowCreateIn(BaseModel):
    venue_id: int
    title: str = Field(min_length=1, max_length=120)
    starts_at: datetime
    regular_price_paise: int = Field(gt=0)
    premium_price_paise: int = Field(gt=0)
