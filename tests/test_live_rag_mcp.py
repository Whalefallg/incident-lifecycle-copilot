"""Live rag-as-mcp contract tests; only fixture setup may skip."""
import os
from pathlib import Path
import pytest
import pytest_asyncio
from agents.consultant.mcp_rag_client import McpRagClient
from config.rag_mcp import RagMcpSettings


@pytest_asyncio.fixture
async def live_client():
    raw_path = os.getenv("RAG_MCP_SERVER_PATH")
    if not raw_path:
        pytest.skip("RAG_MCP_SERVER_PATH is not configured")
    server_path = Path(raw_path)
    if not (server_path / "main.py").is_file():
        pytest.skip("RAG_MCP_SERVER_PATH does not contain main.py")
    raw_settings = os.getenv("RAG_MCP_SETTINGS_PATH")
    settings_path = Path(raw_settings) if raw_settings else server_path / "config" / "settings.yaml"
    if not settings_path.is_file():
        pytest.skip("rag-as-mcp settings file is unavailable before setup")
    client = McpRagClient(RagMcpSettings(mode="mcp", server_path=server_path, python_executable=os.getenv("RAG_MCP_PYTHON"), settings_path=settings_path))
    await client.start()
    yield client
    await client.stop()


@pytest.mark.live
@pytest.mark.asyncio
async def test_initialize_and_current_capabilities(live_client):
    assert live_client.capabilities.server_name == "rag-as-mcp"
    assert live_client.capabilities.server_version
    assert "query_knowledge_hub" in live_client.capabilities.tools


@pytest.mark.live
@pytest.mark.asyncio
async def test_process_health_ping(live_client):
    await live_client.ping()


@pytest.mark.live
@pytest.mark.asyncio
async def test_known_query_crosses_stdio_boundary(live_client):
    results = await live_client.query("What is the Redis OOM runbook?", top_k=3)
    # An empty list is a valid retrieval result when the configured collection
    # has not been ingested; backend failures and malformed responses still raise.
    assert isinstance(results, list) and len(results) <= 3
    assert all(result.content and result.source and result.document_id for result in results)
