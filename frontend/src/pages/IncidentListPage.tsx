import { useQuery } from "@tanstack/react-query";

import { ApiError, api } from "../api/client";
import { AsyncState } from "../components/common/AsyncState";
import { CreateIncidentForm } from "../features/incidents/CreateIncidentForm";
import { IncidentTable } from "../features/incidents/IncidentTable";

export function IncidentListPage() {
  const incidents = useQuery({ queryKey: ["incidents"], queryFn: api.listIncidents });

  return (
    <div className="page-stack">
      <section className="page-header">
        <div><span className="eyebrow">Operations workspace</span><h1>Incidents</h1><p>Recoverable workflows and recorded operational facts.</p></div>
        <CreateIncidentForm />
      </section>
      {incidents.isPending ? <AsyncState title="Loading incidents" description="Reading the latest snapshots from the server." /> : null}
      {incidents.isError ? (
        <AsyncState
          title="Unable to load incidents"
          description={incidents.error instanceof ApiError ? incidents.error.message : "The incident service could not be reached."}
          action={<button type="button" onClick={() => void incidents.refetch()}>Retry</button>}
        />
      ) : null}
      {incidents.data?.total === 0 ? <AsyncState title="No incidents yet" description="Create a demo incident to start the lifecycle." /> : null}
      {incidents.data && incidents.data.total > 0 ? <section className="panel"><IncidentTable incidents={incidents.data.items} /></section> : null}
    </div>
  );
}
