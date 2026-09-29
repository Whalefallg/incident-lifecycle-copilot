from collections.abc import AsyncIterator, Callable
from uuid import NAMESPACE_URL, uuid5

from pydantic import TypeAdapter

from api.chat_handler import ConversationCoordinator
from api.contracts.incidents import CreateMessageRequest
from api.contracts.streaming import (
    ErrorPayload,
    IncidentEventPayload,
    IncidentRecordedEvent,
    MessageCompletedEvent,
    MessageCompletedPayload,
    PostmortemGeneratedEvent,
    PostmortemGeneratedPayload,
    RequestCompletedEvent,
    RequestCompletedPayload,
    RequestStartedEvent,
    RetrievalCompletedEvent,
    RetrievalCompletedPayload,
    StreamErrorEvent,
    StreamEvent,
    WorkflowStateChangedEvent,
    WorkflowStateChangedPayload,
)
from api.core.exceptions import ErrorCode
from conversation.repository import (
    ConcurrentConversationUpdate,
    ConversationRepository,
    IdempotencyKeyMismatch,
    RequestInProgress,
)

CoordinatorFactory = Callable[[ConversationRepository], ConversationCoordinator]
_event_adapter = TypeAdapter(StreamEvent)


def serialize_sse(event: StreamEvent) -> str:
    data = _event_adapter.dump_json(event, by_alias=True).decode("utf-8")
    return f"id: {event.event_id}\nevent: {event.type}\ndata: {data}\n\n"


class IncidentStreamingService:
    """Expose request progress and committed coordinator results as typed SSE."""

    def __init__(
        self,
        repository: ConversationRepository,
        coordinator_factory: CoordinatorFactory = ConversationCoordinator,
    ) -> None:
        self.repository = repository
        self.coordinator_factory = coordinator_factory

    async def stream_message(
        self, incident_id: str, request: CreateMessageRequest
    ) -> AsyncIterator[str]:
        before = await self.repository.load(incident_id)
        if before is None:
            return

        sequence = 0

        def envelope(event_type, payload):
            nonlocal sequence
            event = event_type(
                incident_id=incident_id,
                request_id=request.request_id,
                sequence=sequence,
                payload=payload,
            )
            sequence += 1
            return event

        yield serialize_sse(envelope(RequestStartedEvent, {}))

        try:
            coordinator = self.coordinator_factory(self.repository)
            response = await coordinator.process(
                request.message,
                incident_id,
                request.request_id,
                request_payload={"message": request.message},
            )
            after = await self.repository.load(incident_id)
            if after is None:
                raise RuntimeError("incident snapshot disappeared after processing")

            if after.current_state != before.current_state:
                yield serialize_sse(
                    envelope(
                        WorkflowStateChangedEvent,
                        WorkflowStateChangedPayload(
                            from_state=before.current_state.value,
                            to=after.current_state.value,
                        ),
                    )
                )

            known_event_ids = {event.event_id for event in before.events}
            for incident_event in after.events:
                if incident_event.event_id not in known_event_ids:
                    yield serialize_sse(
                        envelope(
                            IncidentRecordedEvent,
                            IncidentEventPayload(event=incident_event.model_dump(mode="json")),
                        )
                    )

            known_retrieval_ids = {
                retrieval.retrieval_id
                for trace in before.request_traces
                for retrieval in trace.retrievals
            }
            for trace in after.request_traces:
                for retrieval in trace.retrievals:
                    if retrieval.retrieval_id in known_retrieval_ids:
                        continue
                    yield serialize_sse(
                        envelope(
                            RetrievalCompletedEvent,
                            RetrievalCompletedPayload(
                                query=retrieval.query,
                                result_count=len(retrieval.results),
                                duration_ms=retrieval.duration_ms,
                            ),
                        )
                    )

            message_id = str(uuid5(NAMESPACE_URL, f"{incident_id}:{request.request_id}:response"))
            yield serialize_sse(
                envelope(
                    MessageCompletedEvent,
                    MessageCompletedPayload(message_id=message_id, text=response),
                )
            )

            known_drafts = {draft.draft_id for draft in before.postmortem_context.drafts}
            for draft in after.postmortem_context.drafts:
                if draft.draft_id not in known_drafts:
                    yield serialize_sse(
                        envelope(
                            PostmortemGeneratedEvent,
                            PostmortemGeneratedPayload(
                                draft_id=draft.draft_id, version=draft.version
                            ),
                        )
                    )

            yield serialize_sse(
                envelope(
                    RequestCompletedEvent,
                    RequestCompletedPayload(revision=after.revision),
                )
            )
        except Exception as exc:
            code = self._error_code(exc)
            yield serialize_sse(
                envelope(
                    StreamErrorEvent,
                    ErrorPayload(code=code, message=self._error_message(code)),
                )
            )

    @staticmethod
    def _error_code(exc: Exception) -> ErrorCode:
        if isinstance(exc, ConcurrentConversationUpdate):
            return ErrorCode.CONVERSATION_CONFLICT
        if isinstance(exc, IdempotencyKeyMismatch):
            return ErrorCode.IDEMPOTENCY_MISMATCH
        if isinstance(exc, RequestInProgress):
            return ErrorCode.REQUEST_IN_PROGRESS
        return ErrorCode.AGENT_EXECUTION_ERROR

    @staticmethod
    def _error_message(code: ErrorCode) -> str:
        messages = {
            ErrorCode.CONVERSATION_CONFLICT: "Incident was updated by another request",
            ErrorCode.IDEMPOTENCY_MISMATCH: "Request ID was already used with a different payload",
            ErrorCode.REQUEST_IN_PROGRESS: "A request with this ID is still in progress",
            ErrorCode.AGENT_EXECUTION_ERROR: "The agent could not complete this request",
        }
        return messages[code]
