from fastapi.testclient import TestClient

from app import create_app


def test_react_build_is_default_and_supports_client_side_routes():
    client = TestClient(create_app(), raise_server_exceptions=False)
    root = client.get("/")
    workspace = client.get("/incidents/INC-SPA")

    assert root.status_code == 200
    assert workspace.status_code == 200
    assert "Incident Lifecycle Copilot" in workspace.text
    assert "src/main.tsx" not in workspace.text


def test_legacy_jinja_ui_remains_available_under_legacy_prefix():
    response = TestClient(create_app(), raise_server_exceptions=False).get("/legacy")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_api_routes_are_not_shadowed_by_spa_fallback():
    response = TestClient(create_app(), raise_server_exceptions=False).get("/api/monitoring/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
