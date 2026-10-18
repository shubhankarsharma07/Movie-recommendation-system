"""
Test setup. Environment variables are set BEFORE the app is imported, so the
app talks to a throwaway database and the synthetic fixture artifacts.

    pytest                                   # SQLite in a temp folder
    TEST_DATABASE_URL=postgresql+psycopg://user@localhost:5432/cinematch_test pytest
"""
import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
BACKEND_DIR = TESTS_DIR.parent
FIXTURE_ARTIFACTS = TESTS_DIR / "fixtures" / "artifacts"
FIXTURE_VERSION = "v20261001_120000"
ADMIN_EMAIL = "admin@example.com"

_tmp_dir = Path(tempfile.mkdtemp(prefix="cinematch-tests-"))
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_tmp_dir / 'test.db'}"
os.environ["ARTIFACTS_DIR"] = str(FIXTURE_ARTIFACTS)
os.environ["JWT_SECRET"] = "test-secret-for-pytest-only-0123456789abcdef"
os.environ["ADMIN_EMAILS"] = ADMIN_EMAIL
os.environ["BCRYPT_ROUNDS"] = "4"            # fast hashing in tests
os.environ["OPENWEATHER_API_KEY"] = ""
os.environ["CORS_ORIGINS"] = "*"
os.environ["ENABLE_INAPP_RETRAIN"] = "false"

sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(TESTS_DIR))
from make_fixture_artifacts import make_artifacts  # noqa: E402

# (re)generate the small deterministic fixture catalog if it is missing
if not (FIXTURE_ARTIFACTS / "current.txt").is_file():
    make_artifacts(FIXTURE_ARTIFACTS, n_items=120, version=FIXTURE_VERSION)

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services import rating_stats  # noqa: E402
from app.services.model_store import store  # noqa: E402


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_tmp_dir, ignore_errors=True)


@pytest.fixture(scope="session")
def client():
    if engine.dialect.name == "postgresql":
        Base.metadata.drop_all(engine)     # fresh schema for every Postgres test run
    with TestClient(app) as c:
        # Register the admin FIRST (the first user is always an admin anyway)
        r = c.post("/api/auth/register", json={"email": ADMIN_EMAIL, "password": "admin-pass",
                                               "display_name": "Admin"})
        assert r.status_code == 201, r.text
        yield c


@pytest.fixture(scope="session")
def admin_headers(client):
    r = client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": "admin-pass"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def new_user(client):
    """Factory: new_user(name="Aman") -> (headers, user dict)."""
    def _make(name: str = "Tester", password: str = "secret123"):
        email = f"{name.lower().replace(' ', '')}-{uuid.uuid4().hex[:8]}@example.com"
        r = client.post("/api/auth/register", json={"email": email, "password": password, "display_name": name})
        assert r.status_code == 201, r.text
        body = r.json()
        return {"Authorization": f"Bearer {body['access_token']}"}, body["user"]
    return _make


@pytest.fixture
def state():
    return store.state


@pytest.fixture
def restore_model():
    """Put the model store back exactly as it was after a test that swaps it."""
    saved_dir, saved_state, saved_interval = store.artifacts_dir, store.state, store.check_interval
    yield store
    store.artifacts_dir, store.state, store.check_interval = saved_dir, saved_state, saved_interval
    store._seen_marker = store._marker()
    rating_stats.invalidate()


@pytest.fixture
def artifacts_copy(tmp_path):
    """A writable copy of the fixture artifacts folder."""
    target = tmp_path / "artifacts"
    shutil.copytree(FIXTURE_ARTIFACTS, target)
    return target
