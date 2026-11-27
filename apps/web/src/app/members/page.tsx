"use client";

import { useCallback, useEffect, useState } from "react";

import { ErrorNotice } from "@/components/error-notice";
import { InvitationsPanel } from "@/components/invitations-panel";
import { RequireSession } from "@/components/require-session";
import { apiGet, apiRequest, type Member, type Role } from "@/lib/api";
import { useSession } from "@/lib/session";

const ROLES: Role[] = ["org_admin", "project_owner", "project_manager", "member", "auditor"];
const label = (role: string) => role.replace("_", " ");

export default function MembersPage() {
  return (
    <RequireSession>
      <Members />
    </RequireSession>
  );
}

function Members() {
  const { token, organisationId, me, can } = useSession();
  const [members, setMembers] = useState<Member[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const manage = can("members.manage");

  const load = useCallback(async () => {
    try {
      setMembers(await apiGet<Member[]>("/api/v1/organisations/current/members", { token, organisationId }));
      setError(null);
    } catch (err) {
      setError(err);
    }
  }, [token, organisationId]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  async function changeRole(userId: string, role: Role) {
    try {
      await apiRequest("PATCH", `/api/v1/organisations/current/members/${userId}`, {
        token,
        organisationId,
        body: { role },
      });
      await load();
    } catch (err) {
      setError(err);
    }
  }

  return (
    <>
      <h1>Members</h1>
      <p className="lede">
        {manage
          ? "Invite people and change roles here."
          : "Everyone in this organisation and their role."}
      </p>
      <ErrorNotice error={error} />
      {members === null ? (
        <p role="status">Loading…</p>
      ) : (
        <table className="table stack">
          <thead>
            <tr>
              <th>Name</th>
              <th>Email</th>
              <th>Role</th>
            </tr>
          </thead>
          <tbody>
            {members.map((m) => (
              <tr key={m.user_id}>
                <td data-l="Name">
                  {m.display_name ?? <span className="muted">No name</span>}
                  {m.user_id === me?.id ? <span className="muted"> (you)</span> : null}
                </td>
                <td data-l="Email">{m.email ?? <span className="muted">None</span>}</td>
                <td data-l="Role">
                  {manage ? (
                    <select
                      aria-label={`Role for ${m.display_name ?? m.email ?? "member"}`}
                      value={m.role}
                      onChange={(e) => void changeRole(m.user_id, e.target.value as Role)}
                    >
                      {ROLES.map((r) => (
                        <option key={r} value={r}>
                          {label(r)}
                        </option>
                      ))}
                    </select>
                  ) : (
                    label(m.role)
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {manage ? <InvitationsPanel /> : null}
    </>
  );
}
