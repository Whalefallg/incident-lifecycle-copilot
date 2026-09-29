const workflowDescriptions: Record<string, string> = {
  classify: "Classifying the request and selecting the responsible workflow.",
  escalation: "Collecting incident context and coordinating on-call escalation.",
  runbook_lookup: "Consulting operational knowledge and relevant runbooks.",
  comms_drafting: "Preparing stakeholder-specific incident communication.",
  postmortem: "Building a review from the structured incident event ledger.",
  other: "Waiting for an incident lifecycle request.",
};

export function WorkflowStatePanel({ state }: { state: string }) {
  return (
    <section className="workflow-card" aria-labelledby="workflow-state-title">
      <div className="workflow-state-heading"><span className="activity-dot activity-running" aria-hidden="true" /><div><span className="eyebrow">Workflow state</span><h2 id="workflow-state-title">{state.replaceAll("_", " ")}</h2></div></div>
      <p>{workflowDescriptions[state] ?? "Server-managed workflow state."}</p>
      <small>Source: ConversationSnapshot</small>
    </section>
  );
}
