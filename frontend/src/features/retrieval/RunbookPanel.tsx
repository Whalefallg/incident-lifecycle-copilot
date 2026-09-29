import { useQuery } from "@tanstack/react-query";

import { ApiError, api } from "../../api/client";
import { AsyncState } from "../../components/common/AsyncState";

function metadataLabel(value: unknown): string {
  return typeof value === "string" || typeof value === "number" ? String(value) : "MCP retrieval";
}

export function RunbookPanel({ incidentId }: { incidentId: string }) {
  const runbooks = useQuery({ queryKey: ["incidents", incidentId, "runbooks"], queryFn: () => api.getIncidentRunbooks(incidentId) });
  return (
    <section className="panel evidence-panel" id="runbooks-panel" role="tabpanel" aria-labelledby="runbooks-tab">
      <div className="panel-heading"><div><span className="eyebrow">Retrieval evidence</span><h2>Runbooks</h2></div>{runbooks.data ? <span>{runbooks.data.total} queries</span> : null}</div>
      {runbooks.isPending ? <p className="empty-inline">Loading retrieval evidence…</p> : null}
      {runbooks.isError ? <AsyncState title="Runbooks unavailable" description={runbooks.error instanceof ApiError ? runbooks.error.message : "Retrieval evidence could not be loaded."} action={<button type="button" onClick={() => void runbooks.refetch()}>Retry</button>} /> : null}
      {runbooks.data?.total === 0 ? <p className="empty-inline">No runbooks have been retrieved for this incident.</p> : null}
      <div className="runbook-groups">
        {runbooks.data?.items.map((retrieval) => <section className="retrieval-group" key={retrieval.retrieval_id}><header><div><strong>{retrieval.query}</strong><small>{retrieval.collection} · {retrieval.duration_ms} ms · {retrieval.results.length} results</small></div></header><div className="runbook-grid">{retrieval.results.map((result) => <article className="runbook-card" key={`${retrieval.retrieval_id}-${result.document_id}`}><div className="runbook-title"><strong>{result.document_id.replaceAll("-", " ")}</strong>{result.score === null ? null : <span>{Math.round(result.score * 100)}%</span>}</div><dl><div><dt>Source</dt><dd>{result.source}</dd></div><div><dt>Backend</dt><dd>{metadataLabel(result.metadata.backend)}</dd></div></dl><p>{result.content}</p></article>)}</div></section>)}
      </div>
    </section>
  );
}
