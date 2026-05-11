import pytest
from fastapi.testclient import TestClient


def test_list_my_workspaces(auth_client: TestClient):
    response = auth_client.get("/api/v1/workspaces")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    # The user should have one default workspace created during registration
    assert len(data) == 1
    assert data[0]["name"] == "authuser's Workspace"


def test_create_workspace(auth_client: TestClient):
    response = auth_client.post("/api/v1/workspaces", json={"name": "New Test Workspace", "slug": "new-test-ws", "description": "A workspace for testing"})
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "New Test Workspace"
    assert data["slug"] == "new-test-ws"


def test_get_workspace(auth_client: TestClient):
    # First create one
    auth_client.post("/api/v1/workspaces", json={"name": "Get WS", "slug": "get-ws"})

    # Then get it
    response = auth_client.get("/api/v1/workspaces/get-ws")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Get WS"
    assert data["role"] == "owner"


def test_update_workspace(auth_client: TestClient):
    auth_client.post("/api/v1/workspaces", json={"name": "Update WS", "slug": "update-ws"})

    response = auth_client.patch("/api/v1/workspaces/update-ws", json={"name": "Updated Name"})
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Name"


def test_list_members(auth_client: TestClient):
    response = auth_client.get("/api/v1/workspaces/user-1-workspace/members")
    # Wait, the default workspace slug is "user-{id}-workspace" which might have dynamic ID.
    # So let's create a new workspace to be sure about the slug.
    auth_client.post("/api/v1/workspaces", json={"name": "Members WS", "slug": "members-ws"})

    response = auth_client.get("/api/v1/workspaces/members-ws/members")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert data[0]["role"] == "owner"
    assert "username" in data[0]
