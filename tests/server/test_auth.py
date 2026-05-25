from fastapi.testclient import TestClient


def test_register_user(client: TestClient):
    response = client.post("/api/v1/auth/register", json={"email": "test@example.com", "username": "testuser", "password": "testpassword123"})
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "test@example.com"
    assert data["username"] == "testuser"
    assert "id" in data


def test_register_existing_user(client: TestClient):
    # First registration
    client.post("/api/v1/auth/register", json={"email": "test2@example.com", "username": "testuser2", "password": "testpassword123"})
    # Second registration with same email
    response = client.post("/api/v1/auth/register", json={"email": "test2@example.com", "username": "testuser3", "password": "testpassword123"})
    assert response.status_code == 400
    assert "already registered" in response.json()["detail"]


def test_login_success(client: TestClient):
    # Register a user first
    client.post("/api/v1/auth/register", json={"email": "login@example.com", "username": "loginuser", "password": "loginpassword"})

    # Try to login
    response = client.post("/api/v1/auth/token", data={"username": "login@example.com", "password": "loginpassword"})
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["username"] == "loginuser"
    assert data["user"]["email"] == "login@example.com"

    me_response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {data['access_token']}"})
    assert me_response.status_code == 200
    assert me_response.json()["email"] == "login@example.com"


def test_login_failure(client: TestClient):
    response = client.post("/api/v1/auth/token", data={"username": "wronguser", "password": "wrongpassword"})
    assert response.status_code == 401


def test_auth_config_defaults(client: TestClient):
    response = client.get("/api/v1/auth/config")
    assert response.status_code == 200
    data = response.json()
    assert data["password_login_enabled"] is True
    assert data["sso_enabled"] is False
    assert data["sso_login_url"] is None


def test_mock_sso_login_when_enabled(client: TestClient, monkeypatch):
    from dingent.core.config import settings

    monkeypatch.setattr(settings, "SSO_ENABLED", True)
    monkeypatch.setattr(settings, "SSO_PROVIDER", "mock")

    response = client.get("/api/v1/auth/sso/login?next=/", follow_redirects=False)
    assert response.status_code == 307
    assert "/api/v1/auth/sso/callback" in response.headers["location"]

    callback_response = client.get(response.headers["location"], follow_redirects=False)
    assert callback_response.status_code == 307
    assert "/auth/sso/callback" in callback_response.headers["location"]
    assert "token=" in callback_response.headers["location"]
