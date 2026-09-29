import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { ApiError, api } from "../api/client";
import { AsyncState } from "../components/common/AsyncState";
import { SeverityBadge } from "../components/common/SeverityBadge";
import { WorkspaceTabs } from "../components/layout/WorkspaceTabs";
import { AgentActivityPanel } from "../features/agents/AgentActivityPanel";
import { ConversationPanel } from "../features/conversation/ConversationPanel";
import { WorkflowStatePanel } from "../features/incidents/WorkflowStatePanel";
import { IncidentTimeline } from "../features/timeline/IncidentTimeline";
import { useWorkspaceStore } from "../stores/workspaceStore";

export function IncidentWorkspacePage() {
  const { incidentId = "" } = useParams();
  const selectedTab = useWorkspaceStore((state) => state.selectedWorkspaceTab);
  const selectTab = useWorkspaceStore((state) => state.selectWorkspaceTab);
  const stream = useWorkspaceStore((state) => state.streams[incidentId]);
  const incident = useQuery({
    queryKey: ["incidents", incidentId],
    queryFn: () => api.getIncident(incidentId),
    enabled: incidentId.length > 0,
  });
  const timeline = useQuery({
    queryKey: ["incidents", incidentId, "events"],
    queryFn: () => api.getIncidentTimeline(incidentId),
    enabled: incidentId.length > 0,
  });

  if (incident.isPending) return <AsyncState title="Loading incident" description="Restoring the current server snapshot." />;
  if (incident.isError) {
    return <AsyncState title={incident.error instanceof ApiError && incident.error.status === 404 ? "Incident not found" : "Unable to load incident"} description={incident.error instanceof ApiError ? incident.error.message : "The incident service could not be reached."} action={<Link className="button-link" to="/incidents">Back to incidents</Link>} />;
  }

  const workflowState = stream?.workflowState ?? incident.data.workflow_state;
  const agentActivities = Object.values(stream?.agents ?? {});

  return (
    <div className="workspace-page">
      <section className="workspace-header">
        <div><Link className="back-link" to="/incidents">← All incidents</Link><span className="incident-id">{incident.data.incident_id}</span><h1>{incident.data.title}</h1></div>
        <div className="header-badges"><SeverityBadge severity={incident.data.severity} /><span className={`status status-${incident.data.status}`}>{incident.data.status}</span></div>
      </section>
      <section className="metric-strip" aria-label="Incident metadata">
        <div><span>Service</span><strong>{incident.data.service ?? "Not set"}</strong></div>
        <div><span>Workflow state</span><strong>{workflowState}</strong></div>
        <div><span>Revision</span><strong>{incident.data.revision}</strong></div>
        <div><span>Last update</span><strong>{new Date(incident.data.updated_at).toLocaleString()}</strong></div>
      </section>
      <WorkspaceTabs selected={selectedTab} timelineCount={timeline.data?.total ?? null} onSelect={selectTab} />
      <div className="workspace-grid">
        <div className="workspace-main">
          {selectedTab === "conversation" ? <ConversationPanel incidentId={incidentId} /> : null}
          {selectedTab === "timeline" ? (
            <section className="panel timeline-panel" id="timeline-panel" role="tabpanel" aria-labelledby="timeline-tab">
              <div className="panel-heading"><div><span className="eyebrow">Event ledger</span><h2>Timeline</h2></div>{timeline.data ? <span>{timeline.data.total} events</span> : null}</div>
              {timeline.isPending ? <p className="empty-inline">Loading recorded events…</p> : null}
              {timeline.isError ? <AsyncState title="Timeline unavailable" description={timeline.error instanceof ApiError ? timeline.error.message : "Events could not be loaded."} action={<button type="button" onClick={() => void timeline.refetch()}>Retry</button>} /> : null}
              {timeline.data ? <IncidentTimeline events={timeline.data.items} /> : null}
            </section>
          ) : null}
        </div>
        <aside className="context-sidebar" aria-label="Incident context">
          <WorkflowStatePanel state={workflowState} />
          <section className="panel context-panel">
            <span className="eyebrow">Current context</span><h2>Incident state</h2>
            <dl><div><dt>Status</dt><dd>{incident.data.status}</dd></div><div><dt>Severity</dt><dd>{incident.data.severity ?? "Not classified"}</dd></div><div><dt>Service</dt><dd>{incident.data.service ?? "Not identified"}</dd></div><div><dt>Revision</dt><dd>{incident.data.revision}</dd></div></dl>
            <p className="context-note">This view is derived from the server-side ConversationSnapshot. Browser state is presentation-only.</p>
          </section>
          <section className="panel agent-panel"><AgentActivityPanel agents={agentActivities} /></section>
        </aside>
      </div>
    </div>
  );
}
