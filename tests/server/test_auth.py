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


def test_login_failure(client: TestClient):
    response = client.post("/api/v1/auth/token", data={"username": "wronguser", "password": "wrongpassword"})
    assert response.status_code == 401
