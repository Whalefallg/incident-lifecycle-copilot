from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from agents.consultant.mcp_rag_client import (
    McpCapabilities,
    McpCapabilityError,
    McpNotConfigured,
    McpProcessExited,
    McpRagClient,
    McpTimeoutError,
)
from agents.consultant.mcp_response_parser import (
    McpMalformedResponse,
    McpQueryResponseParser,
    McpToolError,
    normalize_document_id,
)
from agents.consultant.retrieval import LocalRunbookRetriever, RetrievalResult
from agents.consultant.retrieval_runtime import initialize_retrieval, shutdown_retrieval
from config.rag_mcp import RagMcpSettings

MARKDOWN = """**检索结果**（共 2 条相关内容）

**[1]** `data/documents/default/redis-oom-runbook.pdf`，第 3 页（相关度: 0.912）
> Run MEMORY DOCTOR first.
Then inspect maxmemory and eviction policy.

**[2]** `data/documents/default/cache-policy.md`（相关度: N/A）
> Check maxmemory-policy.

---
*以上内容来自本地知识库，引用编号 [N] 对应上方来源。*
"""


def envelope(text=MARKDOWN, *, is_error=False):
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def tool_schema(maximum=50):
    return {
        "tools": [
            {
                "name": "query_knowledge_hub",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "top_k": {"type": "integer", "maximum": maximum},
                        "collection": {"type": "string"},
                    },
                    "required": ["query"],
                },
            }
        ]
    }


def initialized():
    return {"serverInfo": {"name": "rag-as-mcp", "version": "0.1.0"}}


def test_parser_splits_citations_and_preserves_real_scores():
    results = McpQueryResponseParser().parse(envelope())
    assert [r.document_id for r in results] == ["redis-oom-runbook", "cache-policy"]
    assert results[0].score == pytest.approx(0.912)
    assert "eviction policy" in results[0].content
    assert results[1].score is None
    assert results[0].source.endswith("redis-oom-runbook.pdf")
    assert results[0].metadata["document_id_normalization"] == "incident-source-path-stem"


@pytest.mark.parametrize(
    "path, expected",
    [
        ("data/documents/default/Redis OOM Runbook.PDF", "redis-oom-runbook"),
        (r"C:\\docs\\checkout_error.yaml", "checkout-error"),
    ],
)
def test_source_normalization(path, expected):
    assert normalize_document_id(path) == expected


@pytest.mark.parametrize(
    "text",
    [
        "错误：查询内容不能为空。",
        "检索组件初始化失败，请检查配置。错误：bad embedding",
        "检索时发生错误：collection missing",
    ],
)
def test_upstream_text_errors_are_not_results(text):
    with pytest.raises(McpToolError):
        McpQueryResponseParser().parse(envelope(text))


def test_is_error_true_fails():
    with pytest.raises(McpToolError):
        McpQueryResponseParser().parse(envelope("Error: boom", is_error=True))


def test_no_results_is_distinct_from_failure():
    assert McpQueryResponseParser().parse(envelope("未找到相关内容。请检查知识库。")) == []


def test_malformed_response_fails_explicitly():
    with pytest.raises(McpMalformedResponse):
        McpQueryResponseParser().parse(envelope("some unstructured prose"))


def test_capability_validation_accepts_current_contract():
    caps = McpRagClient._validate_capabilities(initialized(), tool_schema())
    assert caps.server_name == "rag-as-mcp"
    assert caps.tools == ("query_knowledge_hub",)


@pytest.mark.parametrize("tools", [{"tools": []}, tool_schema(maximum=100)])
def test_capability_validation_rejects_missing_or_wrong_schema(tools):
    with pytest.raises(McpCapabilityError):
        McpRagClient._validate_capabilities(initialized(), tools)


@pytest.mark.asyncio
async def test_query_passes_real_tool_contract_and_parses_results():
    client = McpRagClient(RagMcpSettings(server_path=Path("."), max_retries=0))
    client._process = AsyncMock(returncode=None)
    client.capabilities = McpCapabilities("rag-as-mcp", "0.1.0", ("query_knowledge_hub",))
    client._request = AsyncMock(return_value=envelope())
    results = await client.query("redis oom", top_k=7, collection="ops")
    client._request.assert_awaited_once_with(
        "tools/call",
        {
            "name": "query_knowledge_hub",
            "arguments": {"query": "redis oom", "top_k": 7, "collection": "ops"},
        },
    )
    assert len(results) == 2


@pytest.mark.asyncio
async def test_timeout_is_explicit_after_bounded_attempts():
    client = McpRagClient(RagMcpSettings(server_path=Path("."), max_retries=1))
    client._process = AsyncMock(returncode=None)
    client.capabilities = McpCapabilities("rag-as-mcp", "0.1.0", ("query_knowledge_hub",))
    client._request = AsyncMock(side_effect=McpTimeoutError("timeout"))
    client.stop = AsyncMock()
    client.start = AsyncMock()
    with pytest.raises(McpTimeoutError):
        await client.query("redis", top_k=1)
    assert client._request.await_count == 2
    client.start.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_death_is_classified_without_retry_when_disabled():
    client = McpRagClient(RagMcpSettings(server_path=Path("."), max_retries=0))
    client._process = AsyncMock(returncode=9)
    client.capabilities = McpCapabilities("rag-as-mcp", "0.1.0", ("query_knowledge_hub",))
    with pytest.raises(McpProcessExited):
        await client.query("redis", top_k=1)


@pytest.mark.asyncio
async def test_auto_falls_back_only_during_startup(tmp_path):
    retriever = await initialize_retrieval(
        RagMcpSettings(mode="auto", server_path=tmp_path / "missing")
    )
    assert isinstance(retriever, LocalRunbookRetriever)
    await shutdown_retrieval()


@pytest.mark.asyncio
async def test_required_mode_fails_when_not_configured():
    with pytest.raises(McpNotConfigured):
        await initialize_retrieval(RagMcpSettings(mode="mcp", server_path=None))


@pytest.mark.asyncio
async def test_agent_accepts_only_retriever_contract():
    from agents.consultant_agent import ConsultantAgent

    fake = AsyncMock()
    fake.search = AsyncMock(
        return_value=[RetrievalResult(document_id="redis", content="steps", source="redis.md")]
    )
    agent = ConsultantAgent(retriever=fake)
    assert agent.retriever is fake
