import { useQuery } from "@tanstack/react-query";

import { ApiError, api } from "../../api/client";
import { AsyncState } from "../../components/common/AsyncState";
import { IncidentTimeline } from "../timeline/IncidentTimeline";

export function PostmortemPanel({ incidentId }: { incidentId: string }) {
  const postmortem = useQuery({
    queryKey: ["incidents", incidentId, "postmortem"],
    queryFn: () => api.getIncidentPostmortem(incidentId),
  });

  if (postmortem.isPending) {
    return <AsyncState title="Loading postmortem" description="Restoring recorded events and the latest generated draft." />;
  }
  if (postmortem.isError) {
    return <AsyncState title="Postmortem unavailable" description={postmortem.error instanceof ApiError ? postmortem.error.message : "The postmortem could not be loaded."} action={<button type="button" onClick={() => void postmortem.refetch()}>Retry</button>} />;
  }

  const draft = postmortem.data.generated_analysis;
  return (
    <section className="panel postmortem-panel" id="postmortem-panel" role="tabpanel" aria-labelledby="postmortem-tab">
      <div className="panel-heading"><div><span className="eyebrow">Evidence boundary</span><h2>Postmortem review</h2></div>{draft ? <span className={`status status-${draft.status}`}>{draft.status}</span> : null}</div>
      <div className="postmortem-grid">
        <section aria-labelledby="recorded-events-heading">
          <span className="provenance-label fact-label">Recorded facts</span>
          <h2 id="recorded-events-heading">Factual timeline</h2>
          <p className="context-note">These entries come from the persisted incident event ledger.</p>
          <IncidentTimeline events={postmortem.data.factual_timeline} />
        </section>
        <section aria-labelledby="generated-analysis-heading">
          <span className="provenance-label generated-label">Generated analysis</span>
          <h2 id="generated-analysis-heading">Latest draft</h2>
          {draft ? <><p className="draft-meta">Version {draft.version} · created {new Date(draft.created_at).toLocaleString()}</p><article className="draft-content">{draft.content}</article></> : <p className="empty-inline">No generated postmortem draft exists yet. Ask the copilot to generate one after resolution.</p>}
        </section>
      </div>
    </section>
  );
}
