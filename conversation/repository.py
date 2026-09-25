"""Conversation persistence with optimistic concurrency and idempotency."""

import asyncio
import json
from abc import ABC, abstractmethod
from redis.asyncio import Redis

from .models import ConversationSnapshot, utc_now


class ConversationRepositoryError(RuntimeError):
    pass


class ConversationAlreadyExists(ConversationRepositoryError):
    pass


class ConcurrentConversationUpdate(ConversationRepositoryError):
    pass


class RequestInProgress(ConversationRepositoryError):
    pass


class IdempotencyKeyMismatch(ConversationRepositoryError):
    """A request ID was reused with a different canonical payload."""

    pass


class ConversationRepository(ABC):
    @abstractmethod
    async def load(self, session_id: str) -> ConversationSnapshot | None: ...

    @abstractmethod
    async def create(self, snapshot: ConversationSnapshot) -> ConversationSnapshot: ...

    @abstractmethod
    async def save(
        self, snapshot: ConversationSnapshot, expected_revision: int
    ) -> ConversationSnapshot: ...

    @abstractmethod
    async def delete(self, session_id: str) -> None: ...

    @abstractmethod
    async def claim_request(self, request_id: str, fingerprint: str) -> str | None: ...

    @abstractmethod
    async def complete_request(
        self, request_id: str, fingerprint: str, response: str
    ) -> None: ...

    @abstractmethod
    async def abandon_request(self, request_id: str, fingerprint: str) -> None: ...


class InMemoryConversationRepository(ConversationRepository):
    """Process-local implementation intended for tests and single-worker demos."""

    def __init__(self) -> None:
        self._snapshots: dict[str, ConversationSnapshot] = {}
        self._requests: dict[str, dict[str, str | None]] = {}
        self._lock = asyncio.Lock()

    async def load(self, session_id: str) -> ConversationSnapshot | None:
        async with self._lock:
            value = self._snapshots.get(session_id)
            return value.model_copy(deep=True) if value else None

    async def create(self, snapshot: ConversationSnapshot) -> ConversationSnapshot:
        async with self._lock:
            if snapshot.session_id in self._snapshots:
                raise ConversationAlreadyExists(snapshot.session_id)
            stored = snapshot.model_copy(deep=True)
            self._snapshots[snapshot.session_id] = stored
            return stored.model_copy(deep=True)

    async def save(
        self, snapshot: ConversationSnapshot, expected_revision: int
    ) -> ConversationSnapshot:
        async with self._lock:
            current = self._snapshots.get(snapshot.session_id)
            if current is None or current.revision != expected_revision:
                actual = None if current is None else current.revision
                raise ConcurrentConversationUpdate(
                    f"session={snapshot.session_id} expected={expected_revision} actual={actual}"
                )
            stored = snapshot.model_copy(deep=True)
            stored.revision = expected_revision + 1
            stored.updated_at = utc_now()
            self._snapshots[stored.session_id] = stored
            return stored.model_copy(deep=True)

    async def delete(self, session_id: str) -> None:
        async with self._lock:
            self._snapshots.pop(session_id, None)

    async def claim_request(self, request_id: str, fingerprint: str) -> str | None:
        async with self._lock:
            if request_id not in self._requests:
                self._requests[request_id] = {
                    "fingerprint": fingerprint,
                    "response": None,
                }
                return None
            record = self._requests[request_id]
            if record["fingerprint"] != fingerprint:
                raise IdempotencyKeyMismatch(
                    f"request_id={request_id} was reused with a different payload"
                )
            response = record["response"]
            if response is None:
                raise RequestInProgress(request_id)
            return response

    async def complete_request(
        self, request_id: str, fingerprint: str, response: str
    ) -> None:
        async with self._lock:
            record = self._requests.get(request_id)
            if record is None or record["fingerprint"] != fingerprint:
                raise IdempotencyKeyMismatch(request_id)
            record["response"] = response

    async def abandon_request(self, request_id: str, fingerprint: str) -> None:
        async with self._lock:
            record = self._requests.get(request_id)
            if (
                record is not None
                and record["fingerprint"] == fingerprint
                and record["response"] is None
            ):
                self._requests.pop(request_id, None)


class RedisConversationRepository(ConversationRepository):
    """Full-snapshot Redis repository using Lua compare-and-set."""

    SESSION_PREFIX = "incident:session:"
    REQUEST_PREFIX = "incident:request:"

    _CAS_SCRIPT = """
    local raw = redis.call('GET', KEYS[1])
    if not raw then return -1 end
    local current = cjson.decode(raw)
    if tonumber(current['revision']) ~= tonumber(ARGV[1]) then return 0 end
    redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[3])
    return 1
    """

    def __init__(
        self,
        redis: Redis,
        *,
        ttl_seconds: int = 3600,
        request_ttl_seconds: int = 3600,
    ) -> None:
        self._redis = redis
        self._ttl_seconds = ttl_seconds
        self._request_ttl_seconds = request_ttl_seconds

    def _session_key(self, session_id: str) -> str:
        return f"{self.SESSION_PREFIX}{session_id}"

    def _request_key(self, request_id: str) -> str:
        return f"{self.REQUEST_PREFIX}{request_id}"

    async def load(self, session_id: str) -> ConversationSnapshot | None:
        raw = await self._redis.get(self._session_key(session_id))
        return ConversationSnapshot.from_json_payload(raw) if raw else None

    async def create(self, snapshot: ConversationSnapshot) -> ConversationSnapshot:
        created = await self._redis.set(
            self._session_key(snapshot.session_id),
            snapshot.json_payload(),
            ex=self._ttl_seconds,
            nx=True,
        )
        if not created:
            raise ConversationAlreadyExists(snapshot.session_id)
        return snapshot.model_copy(deep=True)

    async def save(
        self, snapshot: ConversationSnapshot, expected_revision: int
    ) -> ConversationSnapshot:
        stored = snapshot.model_copy(deep=True)
        stored.revision = expected_revision + 1
        stored.updated_at = utc_now()
        result = await self._redis.eval(
            self._CAS_SCRIPT,
            1,
            self._session_key(snapshot.session_id),
            expected_revision,
            stored.json_payload(),
            self._ttl_seconds,
        )
        if int(result) != 1:
            raise ConcurrentConversationUpdate(
                f"session={snapshot.session_id} expected={expected_revision}"
            )
        return stored

    async def delete(self, session_id: str) -> None:
        await self._redis.delete(self._session_key(session_id))

    async def claim_request(self, request_id: str, fingerprint: str) -> str | None:
        key = self._request_key(request_id)
        in_progress = json.dumps(
            {"status": "IN_PROGRESS", "fingerprint": fingerprint},
            separators=(",", ":"),
        )
        claimed = await self._redis.set(
            key, in_progress, ex=self._request_ttl_seconds, nx=True
        )
        if claimed:
            return None
        raw = await self._redis.get(key)
        if raw is None:
            raise RequestInProgress(
                f"request_id={request_id} changed while checking idempotency state"
            )
        record = json.loads(raw)
        if record.get("fingerprint") != fingerprint:
            raise IdempotencyKeyMismatch(
                f"request_id={request_id} was reused with a different payload"
            )
        if record.get("status") == "IN_PROGRESS":
            raise RequestInProgress(request_id)
        return record["response"]

    async def complete_request(
        self, request_id: str, fingerprint: str, response: str
    ) -> None:
        completed = json.dumps(
            {
                "status": "COMPLETED",
                "fingerprint": fingerprint,
                "response": response,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        script = """
        local raw = redis.call('GET', KEYS[1])
        if not raw then return -1 end
        local current = cjson.decode(raw)
        if current['fingerprint'] ~= ARGV[1] then return 0 end
        redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[3])
        return 1
        """
        result = await self._redis.eval(
            script,
            1,
            self._request_key(request_id),
            fingerprint,
            completed,
            self._request_ttl_seconds,
        )
        if int(result) != 1:
            raise IdempotencyKeyMismatch(request_id)

    async def abandon_request(self, request_id: str, fingerprint: str) -> None:
        key = self._request_key(request_id)
        script = """
        local raw = redis.call('GET', KEYS[1])
        if not raw then return 0 end
        local current = cjson.decode(raw)
        if current['fingerprint'] == ARGV[1] and current['status'] == 'IN_PROGRESS'
        then return redis.call('DEL', KEYS[1]) end
        return 0
        """
        await self._redis.eval(script, 1, key, fingerprint)
