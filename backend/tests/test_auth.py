import pytest

pytestmark = pytest.mark.anyio


async def test_register_login_and_me(client):
    r = await client.post("/api/auth/register", json={"email": "Ravi@Example.com", "name": "Ravi", "password": "secret123"})
    assert r.status_code == 201
    assert r.json()["user"]["email"] == "ravi@example.com"  # emails are stored in lower case

    r = await client.post("/api/auth/login", json={"email": "ravi@example.com", "password": "secret123"})
    token = r.json()["access_token"]
    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["name"] == "Ravi" and me.json()["role"] == "user"


async def test_duplicate_email_and_wrong_password(client):
    body = {"email": "a@b.com", "name": "A", "password": "secret123"}
    assert (await client.post("/api/auth/register", json=body)).status_code == 201
    assert (await client.post("/api/auth/register", json=body)).status_code == 409
    r = await client.post("/api/auth/login", json={"email": "a@b.com", "password": "wrong-pass"})
    assert r.status_code == 401


async def test_demo_accounts_on_reserved_domain_can_log_in(client, sql):
    from tests.conftest import PW_HASH
    sql("INSERT INTO users (email, name, password_hash) VALUES ('demo@seatlock.test', 'Demo', %s)", (PW_HASH,))
    r = await client.post("/api/auth/login", json={"email": "demo@seatlock.test", "password": "Passw0rd!"})
    assert r.status_code == 200


async def test_short_password_rejected(client):
    r = await client.post("/api/auth/register", json={"email": "x@y.com", "name": "X", "password": "short"})
    assert r.status_code == 422


async def test_protected_routes(client, users):
    assert (await client.post("/api/shows/1/holds", json={"seat_ids": [1]})).status_code == 401
    bad = {"Authorization": "Bearer not-a-token"}
    assert (await client.get("/api/auth/me", headers=bad)).status_code == 401
    [user] = users(1)
    assert (await client.get("/api/admin/dashboard", headers=user["headers"])).status_code == 403
    [admin] = users(1, role="admin")
    assert (await client.get("/api/admin/dashboard", headers=admin["headers"])).status_code == 200
