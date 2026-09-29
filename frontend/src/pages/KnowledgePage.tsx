import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { ApiError, api, type KnowledgeDraft } from "../api/client";
import { AsyncState } from "../components/common/AsyncState";

type Action = "review" | "approve" | "reject";

export function allowedDraftActions(status: KnowledgeDraft["status"]): Action[] {
  if (status === "draft") return ["review", "reject"];
  if (status === "reviewed") return ["approve", "reject"];
  return [];
}

export function KnowledgePage() {
  const queryClient = useQueryClient();
  const [actor, setActor] = useState("");
  const [adminToken, setAdminToken] = useState("");
  const drafts = useQuery({ queryKey: ["knowledge", "drafts"], queryFn: api.listKnowledgeDrafts });
  const decision = useMutation({
    mutationFn: ({ draftId, action }: { draftId: string; action: Action }) =>
      api.transitionKnowledgeDraft(draftId, action, actor.trim(), adminToken),
    onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: ["knowledge", "drafts"] }); },
  });

  if (drafts.isPending) return <AsyncState title="Loading knowledge drafts" description="Reading reviewable drafts from incident snapshots." />;
  if (drafts.isError) return <AsyncState title="Knowledge drafts unavailable" description={drafts.error instanceof ApiError ? drafts.error.message : "The knowledge service could not be reached."} action={<button type="button" onClick={() => void drafts.refetch()}>Retry</button>} />;

  return (
    <div className="page-stack">
      <header className="page-header"><div><span className="eyebrow">Governed knowledge</span><h1>Knowledge lifecycle</h1><p>Review generated postmortems before any future ingestion step.</p></div><span>{drafts.data.total} drafts</span></header>
      <section className="panel review-credentials" aria-labelledby="review-access-heading">
        <div><span className="eyebrow">Mutation access</span><h2 id="review-access-heading">Reviewer identity</h2><p>Credentials stay in this page only and are sent directly with each decision.</p></div>
        <label>Actor<input value={actor} onChange={(event) => setActor(event.target.value)} placeholder="name@example.com" autoComplete="off" /></label>
        <label>Admin token<input type="password" value={adminToken} onChange={(event) => setAdminToken(event.target.value)} placeholder="Required for decisions" autoComplete="off" /></label>
      </section>
      {decision.isError ? <div className="stream-error" role="alert">{decision.error instanceof ApiError ? decision.error.message : "The decision could not be saved."}</div> : null}
      {drafts.data.items.length === 0 ? <AsyncState title="No knowledge drafts" description="Generated postmortems will appear here for review." /> : (
        <div className="knowledge-grid">
          {drafts.data.items.map((draft) => (
            <article className="panel knowledge-card" key={draft.draft_id}>
              <header><div><span className="eyebrow">Version {draft.version}</span><h2><Link to={`/incidents/${encodeURIComponent(draft.source_incident_id)}`}>{draft.source_incident_id}</Link></h2></div><span className={`status status-${draft.status}`}>{draft.status}</span></header>
              <p className="draft-meta">Created {new Date(draft.created_at).toLocaleString()}</p>
              <div className="draft-content">{draft.content}</div>
              <footer>
                {allowedDraftActions(draft.status).map((action) => <button className={action === "reject" ? "button-secondary" : ""} type="button" key={action} disabled={!actor.trim() || !adminToken || decision.isPending} onClick={() => decision.mutate({ draftId: draft.draft_id, action })}>{action}</button>)}
                {allowedDraftActions(draft.status).length === 0 ? <small>No pending review action.</small> : null}
              </footer>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
