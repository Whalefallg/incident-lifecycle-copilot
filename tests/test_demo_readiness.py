import uuid

import pytest
from fastapi.testclient import TestClient
from types import SimpleNamespace

from agents.consultant.knowledge_retriever import KnowledgeRetriever
from app import app
from api import chat_handler


def test_browser_session_cookie_is_stable():
    with TestClient(app) as client:
        first = client.get("/api/monitoring/health")
        second = client.get("/api/monitoring/health")

    session_id = first.headers["X-Session-ID"]
    assert str(uuid.UUID(session_id)) == session_id
    assert second.headers["X-Session-ID"] == session_id
    assert "HttpOnly" in first.headers["set-cookie"]


def test_invalid_session_header_is_replaced():
    with TestClient(app) as client:
        response = client.get(
            "/api/monitoring/health", headers={"X-Session-ID": "not-a-uuid"}
        )

    assert response.headers["X-Session-ID"] != "not-a-uuid"
    uuid.UUID(response.headers["X-Session-ID"])


def test_cache_clear_requires_admin_token():
    with TestClient(app) as client:
        response = client.post("/api/monitoring/cache/clear")

    assert response.status_code == 403


def test_knowledge_mutation_requires_admin_token():
    with TestClient(app) as client:
        response = client.post(
            "/api/knowledge/",
            json={"question": "q", "answer": "a", "category": "demo"},
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_local_runbook_fallback_returns_grounded_source(monkeypatch):
    monkeypatch.setenv("RAG_MODE", "local")
    retriever = KnowledgeRetriever()
    await retriever.initialize()

    docs = await retriever.search_knowledge("Redis OOM memory", top_k=2)

    assert docs
    assert docs[0]["source"] == "redis-oom-runbook"
    assert "MEMORY DOCTOR" in docs[0]["content"]


def test_agent_graphs_are_disposable_per_request():
    first = chat_handler._build_session_agents("session-a")
    second = chat_handler._build_session_agents("session-a")

    assert first is not second
    assert first.task_agent is not second.task_agent
    assert first.escalation_agent is not second.escalation_agent


def test_celery_tasks_register_without_missing_agent_modules():
    from config.celery_tasks import celery_app

    assert "tasks.generate_postmortem_async" in celery_app.tasks
    assert "tasks.process_alert_batch_async" in celery_app.tasks
