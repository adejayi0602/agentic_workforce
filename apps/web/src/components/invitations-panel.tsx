"use client";

import { useCallback, useEffect, useId, useState } from "react";

import { ErrorNotice } from "@/components/error-notice";
import { apiGet, apiRequest, type Invitation, type InvitationSent, type Role } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { describeInvitationStatus } from "@/lib/invitations";
import { useSession } from "@/lib/session";

const ROLES: Role[] = ["member", "project_manager", "project_owner", "auditor", "org_admin"];
const label = (role: string) => role.replaceAll("_", " ");

/** Invite people by email and manage open invitations. Shown to members.manage holders only. */
export function InvitationsPanel({ onChange }: { onChange?: () => void }) {
  const { token, organisationId } = useSession();
  const [invitations, setInvitations] = useState<Invitation[] | null>(null);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("member");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const hintId = useId();

  const load = useCallback(async () => {
    try {
      setInvitations(
        await apiGet<Invitation[]>("/api/v1/organisations/current/invitations", { token, organisationId }),
      );
    } catch (err) {
      setError(err);
    }
  }, [token, organisationId]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  async function invite(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const sent = await apiRequest<InvitationSent>("POST", "/api/v1/organisations/current/invitations", {
        token,
        organisationId,
        body: { email: email.trim(), role },
      });
      setNotice(
        sent.email_sent
          ? `Invitation sent to ${sent.email}.`
          : `Invitation created for ${sent.email}, but the email could not be sent. Revoke it and try again.`,
      );
      setEmail("");
      await load();
      onChange?.();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function revoke(invitation: Invitation) {
    setError(null);
    setNotice(null);
    try {
      await apiRequest("DELETE", `/api/v1/organisations/current/invitations/${invitation.id}`, {
        token,
        organisationId,
      });
      setNotice(`Invitation for ${invitation.email} revoked.`);
      await load();
    } catch (err) {
      setError(err);
    }
  }

  return (
    <section aria-labelledby="invite-heading" className="stack">
      <h2 id="invite-heading">Invite people</h2>
      <form className="card form" onSubmit={(e) => void invite(e)}>
        <label>
          Email address
          <input
            type="email"
            required
            autoComplete="off"
            value={email}
            aria-describedby={hintId}
            onChange={(e) => setEmail(e.target.value)}
          />
        </label>
        <p id={hintId} className="muted">
          They join when they sign in with this address and accept. Links expire after 7 days and work once.
        </p>
        <label>
          Role
          <select aria-label="Role" value={role} onChange={(e) => setRole(e.target.value as Role)}>
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {label(r)}
              </option>
            ))}
          </select>
        </label>
        <ErrorNotice error={error} />
        {notice ? (
          <p className="notice" role="status">
            {notice}
          </p>
        ) : null}
        <button type="submit" className="button button-primary" disabled={busy || !email.trim()}>
          {busy ? "Sending…" : "Send invitation"}
        </button>
      </form>

      <h3>Invitations</h3>
      {invitations === null ? (
        <p role="status">Loading…</p>
      ) : invitations.length === 0 ? (
        <p className="muted">No invitations yet.</p>
      ) : (
        <table className="table stack">
          <thead>
            <tr>
              <th>Email</th>
              <th>Role</th>
              <th>Status</th>
              <th>Expires</th>
              <th>
                <span className="visually-hidden">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {invitations.map((i) => {
              const status = describeInvitationStatus(i.status);
              return (
                <tr key={i.id}>
                  <td data-l="Email">{i.email}</td>
                  <td data-l="Role">{label(i.role)}</td>
                  <td data-l="Status">
                    <span className={`pill pill-tone-${status.tone}`}>{status.label}</span>
                  </td>
                  <td data-l="Expires">{i.status === "pending" ? formatDate(i.expires_at) : "—"}</td>
                  <td>
                    {i.status === "pending" ? (
                      <button
                        type="button"
                        className="button"
                        aria-label={`Revoke invitation for ${i.email}`}
                        onClick={() => void revoke(i)}
                      >
                        Revoke
                      </button>
                    ) : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}
