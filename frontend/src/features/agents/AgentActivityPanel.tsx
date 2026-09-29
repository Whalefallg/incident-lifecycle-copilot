import type { AgentActivity } from "../../stores/workspaceStore";

const agentLabels: Record<string, string> = {
  TriageRouter: "Triage Router",
  EscalationAgent: "Escalation Agent",
  ConsultantAgent: "Runbook Consultant",
  CommunicationAgent: "Communication Agent",
  PostmortemAgent: "Postmortem Agent",
  "rag-as-mcp": "RAG Retriever",
};

export function AgentActivityPanel({ agents }: { agents: AgentActivity[] }) {
  return (
    <section className="context-section" aria-labelledby="agent-activity-title">
      <span className="eyebrow">Current request</span>
      <h2 id="agent-activity-title">Agent activity</h2>
      {agents.length === 0 ? <p className="empty-inline">No Agent execution recorded in this browser session.</p> : (
        <ul className="agent-list">
          {[...agents].sort((left, right) => left.sequence - right.sequence).map((agent) => (
            <li key={agent.name}>
              <span className={`activity-dot activity-${agent.status}`} aria-hidden="true" />
              <div><strong>{agentLabels[agent.name] ?? agent.name}</strong><small>{agent.status}{agent.durationMs === null ? "" : ` · ${agent.durationMs} ms`}</small></div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
