"""Auth & profile (CONTRACT 5.1, NFR-2)."""
import logging
import uuid

from sqlalchemy import select

from app.database import SessionLocal
from app.models import User
from tests.conftest import ADMIN_EMAIL


def test_register_login_me(client):
    email = f"neha-{uuid.uuid4().hex[:6]}@example.com"
    r = client.post("/api/auth/register", json={"email": email, "password": "hunter22", "display_name": "Neha"})
    assert r.status_code == 201
    body = r.json()
    assert body["token_type"] == "bearer" and body["access_token"]
    user = body["user"]
    assert set(user) == {"id", "email", "display_name", "is_admin", "created_at", "rating_count"}
    assert user["email"] == email and user["display_name"] == "Neha"
    assert user["is_admin"] is False and user["rating_count"] == 0
    assert user["created_at"].endswith("Z")

    r = client.post("/api/auth/login", json={"email": email.upper(), "password": "hunter22"})
    assert r.status_code == 200
    token = r.json()["access_token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200 and me.json()["email"] == email


def test_password_is_hashed_with_bcrypt(client):
    email = f"hash-{uuid.uuid4().hex[:6]}@example.com"
    client.post("/api/auth/register", json={"email": email, "password": "plaintext-pw", "display_name": "H"})
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
    assert user.password_hash.startswith("$2") and "plaintext-pw" not in user.password_hash


def test_bad_credentials_and_duplicates(client):
    email = f"dup-{uuid.uuid4().hex[:6]}@example.com"
    assert client.post("/api/auth/register", json={"email": email, "password": "abcdef", "display_name": "D"}).status_code == 201
    r = client.post("/api/auth/register", json={"email": email, "password": "abcdef", "display_name": "D"})
    assert r.status_code == 409
    assert client.post("/api/auth/login", json={"email": email, "password": "wrong!!"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "x"}).status_code == 401


def test_short_password_is_422_and_never_echoed(client):
    r = client.post("/api/auth/register", json={"email": "short@example.com", "password": "abc", "display_name": "S"})
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], str) and "password" in r.json()["detail"]
    assert "abc" not in r.text.replace("abcdef", "")   # the submitted value is not echoed back


def test_me_requires_token(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_first_user_and_admin_emails_are_admins(client, admin_headers, new_user):
    me = client.get("/api/auth/me", headers=admin_headers).json()
    assert me["email"] == ADMIN_EMAIL and me["is_admin"] is True
    _, user = new_user("Normal")
    assert user["is_admin"] is False


def test_passwords_never_logged(client, caplog):
    with caplog.at_level(logging.DEBUG):
        client.post("/api/auth/register", json={"email": f"log-{uuid.uuid4().hex[:6]}@example.com",
                                                "password": "super-secret-pw", "display_name": "L"})
        client.post("/api/auth/login", json={"email": "x@example.com", "password": "another-secret"})
    assert "super-secret-pw" not in caplog.text and "another-secret" not in caplog.text
