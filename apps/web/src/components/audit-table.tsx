import type { AuditEvent } from "@/lib/api";
import { formatDate, humanise } from "@/lib/format";

function summarise(details: Record<string, unknown>): string {
  return Object.entries(details)
    .map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join(", ") : String(value)}`)
    .join(" · ");
}

export function AuditTable({ events }: { events: AuditEvent[] }) {
  if (events.length === 0) return <p className="muted">No events yet.</p>;
  return (
    <table className="table stack">
      <thead>
        <tr>
          <th>When</th>
          <th>Action</th>
          <th>Outcome</th>
          <th>Details</th>
        </tr>
      </thead>
      <tbody>
        {events.map((e) => (
          <tr key={e.id}>
            <td data-l="When" className="nowrap">
              {formatDate(e.created_at)}
            </td>
            <td data-l="Action">{humanise(e.action)}</td>
            <td data-l="Outcome">
              <span className={`pill pill-${e.decision}`}>{e.decision}</span>
            </td>
            <td data-l="Details" className="small">
              {summarise(e.details)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
