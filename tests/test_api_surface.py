from app import create_app


def test_broken_legacy_agent_routes_are_not_registered():
    paths = create_app().openapi()["paths"]

    assert "/api/incident/escalate" not in paths
    assert "/api/task/classify" not in paths
    assert "/api/consultation/ask" not in paths
    assert "/api/knowledge/drafts/{session_id}" not in paths
    assert "/api/incidents" in paths
    assert "/api/knowledge/drafts" in paths
