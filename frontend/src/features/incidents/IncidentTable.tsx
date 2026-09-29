import { Link } from "react-router-dom";

import type { Incident } from "../../api/client";
import { SeverityBadge } from "../../components/common/SeverityBadge";

const dateFormatter = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
});

export function IncidentTable({ incidents }: { incidents: Incident[] }) {
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Incident</th>
            <th>Service</th>
            <th>Severity</th>
            <th>Workflow</th>
            <th>Status</th>
            <th>Updated</th>
          </tr>
        </thead>
        <tbody>
          {incidents.map((incident) => (
            <tr key={incident.incident_id}>
              <td>
                <Link to={`/incidents/${encodeURIComponent(incident.incident_id)}`}>
                  <strong>{incident.title}</strong>
                  <small>{incident.incident_id}</small>
                </Link>
              </td>
              <td>{incident.service ?? "—"}</td>
              <td><SeverityBadge severity={incident.severity} /></td>
              <td><code>{incident.workflow_state}</code></td>
              <td><span className={`status status-${incident.status}`}>{incident.status}</span></td>
              <td>{dateFormatter.format(new Date(incident.updated_at))}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
