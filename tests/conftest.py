"""Isolated API tests. These fixtures never connect to the deployed database."""

import importlib
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEST_PIN = "only-for-local-tests-12345"
TEST_SECRET = "fabtrace-local-tests-only-secret-not-for-production-123456"
BADGES = {
    "admin": "TEST-ADMIN",
    "supervisor": "TEST-SUPERVISOR",
    "inspector": "TEST-QA",
    "welder": "TEST-WELDER",
    "handler": "TEST-HANDLER",
    "fitup_welder": "TEST-FITUP-WELDER",
    "process_welder": "TEST-PROCESS-WELDER",
    "painter": "TEST-PAINTER",
    "finisher": "TEST-FINISHER",
    "misc": "TEST-MISC",
}


@pytest.fixture(scope="session")
def application(tmp_path_factory):
    # Override rather than inherit DATABASE_URL: test execution must never use
    # production credentials that happen to exist in the invoking environment.
    test_dir = tmp_path_factory.mktemp("fabtrace-import")
    settings = {
        "DATABASE_URL": "sqlite:///" + str(test_dir / "import-only.sqlite"),
        "JWT_SECRET": TEST_SECRET,
        "COOKIE_SECURE": "false",
        "PUBLIC_BASE_URL": "http://testserver",
    }
    previous = {key: os.environ.get(key) for key in settings}
    os.environ.update(settings)
    module = importlib.import_module("main")
    yield module
    module.engine.dispose()
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


@pytest.fixture(scope="session")
def pin_hash(application):
    return application.password_hash.hash(TEST_PIN)


class TestAPI:
    """Use the real authentication dependency with local, signed test cookies."""

    def __init__(self, application, session_factory):
        self.application = application
        self.session_factory = session_factory
        self.client = TestClient(application.app)

    def request(self, method, path, role="admin", **kwargs):
        self.client.cookies.clear()
        if role is not None:
            token = self.application.jwt.encode(
                {
                    "sub": BADGES.get(role, role),
                    "exp": self.application.utcnow()
                    + self.application.dt.timedelta(hours=1),
                },
                self.application.JWT_SECRET,
                algorithm="HS256",
            )
            self.client.cookies.set("fabtrace_session", token)
        return self.client.request(method, path, **kwargs)

    def get(self, path, role="admin", **kwargs):
        return self.request("GET", path, role, **kwargs)

    def post(self, path, body=None, role="admin", **kwargs):
        return self.request("POST", path, role, json=body, **kwargs)

    def put(self, path, body=None, role="admin", **kwargs):
        return self.request("PUT", path, role, json=body, **kwargs)

    def patch(self, path, body=None, role="admin", **kwargs):
        return self.request("PATCH", path, role, json=body, **kwargs)

    def item(self, item_id="TEST-SPOOL-01", welds_required=1, kind="Part"):
        response = self.post(
            "/api/items",
            {
                "id": item_id,
                "description": "Isolated test spool",
                "kind": kind,
                "project": "Test job",
                "drawing": "TEST-DWG Rev A",
                "location": "Test weld bay",
                "handler": BADGES["welder"],
                "welds_required": welds_required,
            },
        )
        assert response.status_code == 201, response.text
        return response.json()


@pytest.fixture
def api(application, pin_hash, tmp_path):
    engine = create_engine(
        "sqlite:///" + str(tmp_path / "test.sqlite"),
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    session_factory = sessionmaker(engine, expire_on_commit=False)
    application.Base.metadata.create_all(engine)
    with session_factory() as session:
        session.add_all(
            application.Employee(
                badge=badge,
                name="Test " + role,
                role=role,
                pin_hash=pin_hash,
                active=True,
            )
            for role, badge in BADGES.items()
        )
        session.commit()

    def test_db():
        with session_factory() as session:
            yield session

    original_overrides = dict(application.app.dependency_overrides)
    application.app.dependency_overrides[application.db] = test_db
    application.failed.clear()
    test_api = TestAPI(application, session_factory)
    yield test_api
    test_api.client.close()
    application.app.dependency_overrides.clear()
    application.app.dependency_overrides.update(original_overrides)
    engine.dispose()
