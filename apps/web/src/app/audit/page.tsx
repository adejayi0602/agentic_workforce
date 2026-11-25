"use client";

import { useCallback, useEffect, useState } from "react";

import { AuditTable } from "@/components/audit-table";
import { ErrorNotice } from "@/components/error-notice";
import { RequireSession } from "@/components/require-session";
import { apiGet, type AuditEvent, type AuditPage } from "@/lib/api";
import { useSession } from "@/lib/session";

export default function AuditPage() {
  return (
    <RequireSession>
      <Audit />
    </RequireSession>
  );
}

function Audit() {
  const { token, organisationId, can } = useSession();
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const allowed = can("audit.read");

  const load = useCallback(
    async (after: string | null) => {
      setLoading(true);
      try {
        const page = await apiGet<AuditPage>("/api/v1/audit-events", {
          token,
          organisationId,
          query: { limit: 50, cursor: after },
        });
        setEvents((current) => (after ? [...current, ...page.items] : page.items));
        setCursor(page.next_cursor ?? null);
        setError(null);
      } catch (err) {
        setError(err);
      } finally {
        setLoading(false);
      }
    },
    [token, organisationId],
  );

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (allowed) void load(null);
  }, [allowed, load]);

  if (!allowed) {
    return (
      <div className="card">
        <h1>Audit</h1>
        <p>Only org admins and auditors can read the audit trail.</p>
      </div>
    );
  }

  return (
    <>
      <h1>Audit trail</h1>
      <p className="lede">Every consequential action in this organisation, including refused attempts.</p>
      <ErrorNotice error={error} />
      <section className="card">
        <AuditTable events={events} />
        {loading ? <p role="status">Loading…</p> : null}
        {cursor && !loading ? (
          <button type="button" className="button" onClick={() => void load(cursor)}>
            Load more
          </button>
        ) : null}
      </section>
    </>
  );
}
