import { useQuery } from "@tanstack/react-query";

import { ApiError, api } from "../../api/client";
import { AsyncState } from "../../components/common/AsyncState";

export function TracePanel({ incidentId }: { incidentId: string }) {
  const traces = useQuery({ queryKey: ["incidents", incidentId, "trace"], queryFn: () => api.getIncidentTrace(incidentId) });
  return (
    <section className="panel evidence-panel" id="trace-panel" role="tabpanel" aria-labelledby="trace-tab">
      <div className="panel-heading"><div><span className="eyebrow">Execution metadata</span><h2>Agent Trace</h2></div>{traces.data ? <span>{traces.data.total} requests</span> : null}</div>
      <p className="trace-disclosure">Shows actions, status, duration, and retrieval counts. Private model reasoning is never recorded.</p>
      {traces.isPending ? <p className="empty-inline">Loading execution trace…</p> : null}
      {traces.isError ? <AsyncState title="Trace unavailable" description={traces.error instanceof ApiError ? traces.error.message : "Execution metadata could not be loaded."} action={<button type="button" onClick={() => void traces.refetch()}>Retry</button>} /> : null}
      {traces.data?.total === 0 ? <p className="empty-inline">No Agent requests have completed for this incident.</p> : null}
      <div className="trace-list">{traces.data?.items.map((trace) => <article className="trace-request" key={trace.trace_id}><header><div><strong>Request {trace.request_id}</strong><small>Trace {trace.trace_id} · {new Date(trace.started_at).toLocaleTimeString()}</small></div></header><ol>{trace.steps.map((step) => <li key={step.step_id}><span className={`activity-dot activity-${step.status === "completed" ? "completed" : "failed"}`} aria-hidden="true" /><div><strong>{step.agent}</strong><span>{step.action.replaceAll("_", " ")}</span><small>{step.status} · {step.duration_ms} ms{step.error_type ? ` · ${step.error_type}` : ""}</small></div></li>)}</ol>{trace.retrievals.map((retrieval) => <div className="trace-retrieval" key={retrieval.retrieval_id}><strong>Retrieval</strong><span>{retrieval.query}</span><small>{retrieval.result_count} results · {retrieval.duration_ms} ms</small></div>)}</article>)}</div>
    </section>
  );
}
