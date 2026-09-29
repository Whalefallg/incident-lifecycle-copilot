import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { api } from "../../api/client";
import { createMessageOperation, type MessageOperation, type StreamEvent } from "../../api/stream";
import { useWorkspaceStore } from "../../stores/workspaceStore";

export function refreshIncidentQueries(
  queryClient: QueryClient,
  incidentId: string,
  event: StreamEvent,
) {
  if (["incident.event", "workflow.state_changed", "request.completed"].includes(event.type)) {
    return queryClient.invalidateQueries({ queryKey: ["incidents", incidentId] });
  }
  return Promise.resolve();
}

export function ConversationPanel({ incidentId }: { incidentId: string }) {
  const [message, setMessage] = useState("");
  const lastOperation = useRef<MessageOperation | null>(null);
  const queryClient = useQueryClient();
  const stream = useWorkspaceStore((state) => state.streams[incidentId]);
  const startStream = useWorkspaceStore((state) => state.startStream);
  const applyStreamEvent = useWorkspaceStore((state) => state.applyStreamEvent);
  const failStream = useWorkspaceStore((state) => state.failStream);
  const messages = useQuery({
    queryKey: ["incidents", incidentId, "messages"],
    queryFn: () => api.getIncidentMessages(incidentId),
  });

  const handleEvent = (event: StreamEvent) => {
    applyStreamEvent(incidentId, event);
    void refreshIncidentQueries(queryClient, incidentId, event);
  };

  const runOperation = async (operation: MessageOperation) => {
    startStream(incidentId, operation.requestId);
    try {
      await operation.run();
      await queryClient.invalidateQueries({ queryKey: ["incidents", incidentId, "messages"] });
    } catch (error) {
      failStream(incidentId, error instanceof Error ? error.message : "The request failed");
    }
  };

  return (
    <section className="panel conversation-panel" id="conversation-panel" role="tabpanel" aria-labelledby="conversation-tab">
      <div className="panel-heading"><div><span className="eyebrow">Copilot</span><h2>Conversation</h2></div>{stream?.status === "streaming" ? <span>Running</span> : null}</div>
      <div className="message-list" aria-live="polite">
        {messages.isPending ? <p className="empty-inline">Loading conversation…</p> : null}
        {messages.isError ? <div className="inline-error" role="alert"><span>Conversation could not be loaded.</span><button className="button-secondary" type="button" onClick={() => void messages.refetch()}>Retry</button></div> : null}
        {messages.data?.total === 0 && !stream?.text ? <p className="empty-inline">Ask the Copilot to triage, investigate, communicate, or resolve this incident.</p> : null}
        {messages.data?.items.map((item, index) => <article className={`message message-${item.role}`} key={`${item.timestamp}-${index}`}><strong>{item.role === "engineer" ? "Engineer" : "Copilot"}</strong><p>{item.content}</p></article>)}
        {stream?.text && stream.status === "streaming" ? <article className="message message-agent"><strong>Copilot</strong><p>{stream.text}<span className="stream-cursor" aria-hidden="true" /></p></article> : null}
      </div>
      {stream?.status === "error" ? <div className="stream-error" role="alert"><span>{stream.error}</span><button type="button" className="button-secondary" onClick={() => lastOperation.current ? void runOperation(lastOperation.current) : undefined}>Retry same request</button></div> : null}
      <form className="message-composer" onSubmit={(event) => { event.preventDefault(); const trimmed = message.trim(); if (!trimmed) return; const operation = createMessageOperation(incidentId, trimmed, handleEvent); lastOperation.current = operation; setMessage(""); void runOperation(operation); }}>
        <label htmlFor="incident-message">Message the Copilot</label>
        <div><textarea id="incident-message" value={message} onChange={(event) => setMessage(event.target.value)} placeholder="Describe the incident or ask for a runbook…" disabled={stream?.status === "streaming"} /><button type="submit" disabled={!message.trim() || stream?.status === "streaming"}>Send</button></div>
      </form>
    </section>
  );
}
