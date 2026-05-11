import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from dingent.core.db.models import Role  # noqa: F401
from dingent.server.api.dependencies import get_db_session
from dingent.server.app import create_app

# Use an in-memory SQLite database for testing
sqlite_url = "sqlite://"

engine = create_engine(
    sqlite_url,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


@pytest.fixture(name="session")
def session_fixture():
    SQLModel.metadata.create_all(engine)

    # Create default roles required by the app
    with Session(engine) as session:
        from sqlmodel import select

        required_roles = ["admin", "user", "guest"]
        for role_name in required_roles:
            role = session.exec(select(Role).where(Role.name == role_name)).first()
            if not role:
                session.add(Role(name=role_name, description=f"Default {role_name} role"))
        session.commit()

    with Session(engine) as session:
        yield session

    SQLModel.metadata.drop_all(engine)


@pytest.fixture(name="app")
def app_fixture():
    app = create_app()
    return app


@pytest.fixture(name="client")
def client_fixture(app, session: Session):
    def get_session_override():
        return session

    app.dependency_overrides[get_db_session] = get_session_override

    # Use context manager to trigger lifespan events (startup/shutdown)
    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture(name="auth_client")
def auth_client_fixture(client: TestClient):
    # Register
    client.post("/api/v1/auth/register", json={"email": "auth@example.com", "username": "authuser", "password": "authpassword"})
    # Login
    response = client.post("/api/v1/auth/token", data={"username": "auth@example.com", "password": "authpassword"})
    token = response.json()["access_token"]

    # Create a new client with the token
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client
