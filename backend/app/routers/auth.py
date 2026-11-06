from fastapi import APIRouter, Depends, HTTPException
from psycopg import errors

from app.db import get_conn
from app.schemas import LoginIn, RegisterIn
from app.security import create_token, current_user, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _token_out(user: dict) -> dict:
    return {"access_token": create_token(user["id"], user["role"]), "token_type": "bearer",
            "user": {k: user[k] for k in ("id", "email", "name", "role")}}


@router.post("/register", status_code=201)
async def register(body: RegisterIn, conn=Depends(get_conn)):
    try:
        cur = await conn.execute(
            "INSERT INTO users (email, name, password_hash) VALUES (%s, %s, %s) RETURNING id, email, name, role",
            (body.email.lower(), body.name.strip(), hash_password(body.password)))
    except errors.UniqueViolation:
        raise HTTPException(409, "An account with this email already exists")
    return _token_out(await cur.fetchone())


@router.post("/login")
async def login(body: LoginIn, conn=Depends(get_conn)):
    cur = await conn.execute("SELECT * FROM users WHERE email = %s", (body.email.lower(),))
    user = await cur.fetchone()
    if user is None or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(401, "Wrong email or password")
    return _token_out(user)


@router.get("/me")
async def me(user=Depends(current_user)):
    return user
