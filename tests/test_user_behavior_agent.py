"""Tests for the experimental incident-pattern analysis service."""

from services.user_behavior_service import UserBehaviorService


def _service_without_database() -> UserBehaviorService:
    return UserBehaviorService.__new__(UserBehaviorService)


def test_no_activity_returns_explicit_pattern(monkeypatch):
    service = _service_without_database()
    monkeypatch.setattr(service, "get_user_behaviors", lambda *args, **kwargs: [])

    result = service.analyze_user_patterns("engineer-1")

    assert result == {
        "pattern": "no_data",
        "recommendation": "需要更多数据",
    }


def test_incident_workflows_are_counted(monkeypatch):
    service = _service_without_database()
    behaviors = [
        {"action_type": "triage", "created_at": "2026-09-01T00:00:00"},
        {"action_type": "runbook_lookup", "created_at": "2026-09-03T00:00:00"},
        {"action_type": "triage", "created_at": "2026-09-05T00:00:00"},
        {"action_type": "unrelated", "created_at": "2026-09-06T00:00:00"},
    ]
    monkeypatch.setattr(service, "get_user_behaviors", lambda *args, **kwargs: behaviors)

    result = service.analyze_user_patterns("engineer-1")

    assert result["pattern"] == "active_responder"
    assert result["workflow_counts"] == {"triage": 2, "runbook_lookup": 1}
    assert result["total_incident_actions"] == 3
