"""Password hashing (bcrypt) and JWT access tokens."""
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings
from app.db import get_conn

_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_token(user_id: int, role: str) -> str:
    payload = {"sub": str(user_id), "role": role,
               "exp": datetime.now(timezone.utc) + timedelta(hours=settings.jwt_hours)}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


async def current_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer), conn=Depends(get_conn)) -> dict:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    try:
        payload = jwt.decode(creds.credentials, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    cur = await conn.execute("SELECT id, email, name, role FROM users WHERE id = %s", (int(payload["sub"]),))
    user = await cur.fetchone()
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User no longer exists")
    return user


async def admin_user(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admins only")
    return user
