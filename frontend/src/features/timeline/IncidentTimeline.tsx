import type { IncidentEvent } from "../../api/client";

const timeFormatter = new Intl.DateTimeFormat(undefined, { timeStyle: "medium" });

function eventSummary(event: IncidentEvent): string {
  const values = Object.entries(event.payload)
    .map(([key, value]) => `${key}: ${String(value)}`)
    .join(" · ");
  return values || "No additional details recorded";
}

export function IncidentTimeline({ events }: { events: IncidentEvent[] }) {
  if (events.length === 0) {
    return <p className="empty-inline">No incident events recorded yet.</p>;
  }

  return (
    <ol className="timeline">
      {events.map((event) => (
        <li key={event.event_id}>
          <div className="timeline-marker" aria-hidden="true" />
          <div className="timeline-content">
            <div className="timeline-heading">
              <strong>{event.type.replaceAll("_", " ").toUpperCase()}</strong>
              <time dateTime={event.timestamp}>{timeFormatter.format(new Date(event.timestamp))}</time>
            </div>
            <p>{eventSummary(event)}</p>
            <small>Recorded fact · {event.actor} via {event.source}</small>
          </div>
        </li>
      ))}
    </ol>
  );
}
