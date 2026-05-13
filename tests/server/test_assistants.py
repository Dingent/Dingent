from fastapi.testclient import TestClient


def test_list_assistants_empty(auth_client: TestClient):
    # First get the user's workspace
    ws_response = auth_client.get("/api/v1/workspaces")
    assert ws_response.status_code == 200
    workspaces = ws_response.json()
    assert len(workspaces) > 0
    slug = workspaces[0]["slug"]

    # Now list assistants
    response = auth_client.get(f"/api/v1/{slug}/assistants")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_create_assistant(auth_client: TestClient):
    ws_response = auth_client.get("/api/v1/workspaces")
    slug = ws_response.json()[0]["slug"]

    response = auth_client.post(f"/api/v1/{slug}/assistants", json={"name": "Test Assistant", "description": "My test assistant", "instructions": "You are a helpful assistant"})
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Test Assistant"
    assert data["instructions"] == "You are a helpful assistant"
    assert "id" in data


def test_update_assistant(auth_client: TestClient):
    ws_response = auth_client.get("/api/v1/workspaces")
    slug = ws_response.json()[0]["slug"]

    create_resp = auth_client.post(f"/api/v1/{slug}/assistants", json={"name": "To Update", "description": "Will be updated", "instructions": "Update me"})
    assistant_id = create_resp.json()["id"]

    update_resp = auth_client.patch(f"/api/v1/{slug}/assistants/{assistant_id}", json={"name": "Updated Assistant", "description": "Will be updated", "instructions": "Update me"})
    assert update_resp.status_code == 200
    assert update_resp.json()["name"] == "Updated Assistant"
    assert update_resp.json()["instructions"] == "Update me"  # unmodified


def test_delete_assistant(auth_client: TestClient):
    ws_response = auth_client.get("/api/v1/workspaces")
    slug = ws_response.json()[0]["slug"]

    create_resp = auth_client.post(f"/api/v1/{slug}/assistants", json={"name": "To Delete", "description": "Delete me"})
    assistant_id = create_resp.json()["id"]

    delete_resp = auth_client.delete(f"/api/v1/{slug}/assistants/{assistant_id}")
    assert delete_resp.status_code == 204

    # verify deletion
    list_resp = auth_client.get(f"/api/v1/{slug}/assistants")
    assistants = list_resp.json()
    assert not any(a["id"] == assistant_id for a in assistants)
