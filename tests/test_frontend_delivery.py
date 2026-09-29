from pathlib import Path

from fastapi.testclient import TestClient

from app import create_app


def test_spa_mounts_when_explicit_build_exists(tmp_path: Path):
    frontend_dist = tmp_path / "dist"
    frontend_dist.mkdir()
    frontend_dist.joinpath("index.html").write_text(
        "<title>Incident Lifecycle Copilot</title><div id='root'></div>",
        encoding="utf-8",
    )
    client = TestClient(
        create_app(frontend_dist=frontend_dist), raise_server_exceptions=False
    )
    root = client.get("/")
    workspace = client.get("/incidents/INC-SPA")

    assert root.status_code == 200
    assert workspace.status_code == 200
    assert "Incident Lifecycle Copilot" in workspace.text
    assert "id='root'" in workspace.text


def test_backend_app_does_not_require_frontend_build(tmp_path: Path):
    client = TestClient(
        create_app(frontend_dist=tmp_path / "missing"), raise_server_exceptions=False
    )

    assert client.get("/").status_code == 404
    assert client.get("/api/monitoring/health").status_code == 200


def test_legacy_jinja_ui_remains_available_under_legacy_prefix():
    response = TestClient(create_app(), raise_server_exceptions=False).get("/legacy")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_api_routes_are_not_shadowed_by_spa_fallback():
    response = TestClient(create_app(), raise_server_exceptions=False).get("/api/monitoring/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
