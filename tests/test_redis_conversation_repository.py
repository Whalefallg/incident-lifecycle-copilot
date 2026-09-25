import os
import uuid

import pytest
import redis.asyncio as redis
from redis.exceptions import ConnectionError, TimeoutError

from conversation.models import ConversationSnapshot
from conversation.repository import (
    ConcurrentConversationUpdate,
    IdempotencyKeyMismatch,
    RedisConversationRepository,
)

pytestmark = pytest.mark.redis_integration


@pytest.fixture
async def conversation_repository():
    client = redis.from_url(
        os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True
    )
    try:
        await client.ping()
    except (ConnectionError, TimeoutError):
        await client.aclose()
        pytest.skip("Redis is not configured for integration tests")
    repository = RedisConversationRepository(client, ttl_seconds=60)
    yield repository
    await client.aclose()


@pytest.mark.asyncio
async def test_redis_full_snapshot_cas_is_atomic(conversation_repository):
    session_id = f"test:{uuid.uuid4()}"
    created = await conversation_repository.create(
        ConversationSnapshot(session_id=session_id)
    )
    first = created.model_copy(deep=True)
    stale = created.model_copy(deep=True)
    first.escalation_context.service = "checkout"
    await conversation_repository.save(first, 0)
    stale.escalation_context.service = "payments"
    with pytest.raises(ConcurrentConversationUpdate):
        await conversation_repository.save(stale, 0)
    loaded = await conversation_repository.load(session_id)
    assert loaded.revision == 1
    assert loaded.escalation_context.service == "checkout"
    await conversation_repository.delete(session_id)


@pytest.mark.asyncio
async def test_redis_idempotency_fingerprint_mismatch(conversation_repository):
    request_id = f"test:{uuid.uuid4()}"
    assert await conversation_repository.claim_request(request_id, "fingerprint-a") is None
    await conversation_repository.complete_request(
        request_id, "fingerprint-a", "original response"
    )
    assert (
        await conversation_repository.claim_request(request_id, "fingerprint-a")
        == "original response"
    )
    with pytest.raises(IdempotencyKeyMismatch):
        await conversation_repository.claim_request(request_id, "fingerprint-b")
