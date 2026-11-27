"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ErrorNotice } from "@/components/error-notice";
import { RequireSession } from "@/components/require-session";
import { ApiError, apiRequest, type InvitationAccepted, type InvitationPreview } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { forgetInvitation, pendingInvitation, rememberInvitation, tokenFromHash } from "@/lib/invitations";
import { useSession } from "@/lib/session";

export default function AcceptInvitationPage() {
  // Take the token out of the address bar before anything else, then keep it for this tab so
  // it survives the trip through sign-in.
  const [captured, setCaptured] = useState(false);
  useEffect(() => {
    const fromLink = tokenFromHash(window.location.hash);
    if (fromLink) {
      rememberInvitation(fromLink);
      window.history.replaceState(null, "", window.location.pathname);
    }
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setCaptured(true);
  }, []);

  if (!captured) return <p role="status">Loading…</p>;
  return (
    <RequireSession needsOrganisation={false}>
      <Accept />
    </RequireSession>
  );
}

function Accept() {
  const { token, me, selectOrganisation, refresh } = useSession();
  const router = useRouter();
  const [invitationToken] = useState(() => pendingInvitation());
  const [preview, setPreview] = useState<InvitationPreview | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!invitationToken) return;
    apiRequest<InvitationPreview>("POST", "/api/v1/invitations/preview", {
      token,
      body: { token: invitationToken },
    })
      .then(setPreview)
      .catch(setError);
  }, [token, invitationToken]);

  if (!invitationToken) {
    return (
      <div className="card">
        <h1>No invitation found</h1>
        <p>Open the link from your invitation email again.</p>
        <Link className="button" href="/">
          Go to the dashboard
        </Link>
      </div>
    );
  }

  async function accept() {
    setBusy(true);
    setError(null);
    try {
      const joined = await apiRequest<InvitationAccepted>("POST", "/api/v1/invitations/accept", {
        token,
        body: { token: invitationToken },
      });
      forgetInvitation();
      // Reload memberships first, then switch: the switch itself triggers a reload for the
      // new organisation (refresh() would still see the previously selected one).
      await refresh();
      selectOrganisation(joined.organisation_id);
      router.replace("/");
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  function decline() {
    forgetInvitation();
    router.replace("/");
  }

  const wrongAccount =
    preview && me?.email && preview.email !== me.email.trim().toLowerCase() ? preview.email : null;
  const unusable = preview && preview.status !== "pending";
  const notFound = error instanceof ApiError && error.status === 404;

  return (
    <div className="sign-in">
      <h1>Join an organisation</h1>
      {preview === null && !error ? <p role="status">Loading…</p> : null}
      {preview ? (
        <div className="card stack">
          <p>
            {preview.invited_by ?? "Someone"} invited you to join <strong>{preview.organisation_name}</strong> as{" "}
            <strong>{preview.role.replaceAll("_", " ")}</strong>.
          </p>
          {unusable ? (
            <p className="notice notice-error" role="alert">
              {preview.status === "accepted"
                ? "This invitation has already been used."
                : preview.status === "revoked"
                  ? "This invitation has been withdrawn."
                  : "This invitation has expired. Ask for a new one."}
            </p>
          ) : wrongAccount ? (
            <p className="notice notice-error" role="alert">
              This invitation is for {wrongAccount}, but you&apos;re signed in as {me?.email}. Sign out and sign in
              with the invited address to accept it.
            </p>
          ) : (
            <p className="muted">Expires {formatDate(preview.expires_at)}.</p>
          )}
          <ErrorNotice error={error} />
          <div className="actions">
            {!unusable && !wrongAccount ? (
              <button type="button" className="button button-primary" disabled={busy} onClick={() => void accept()}>
                {busy ? "Joining…" : "Accept invitation"}
              </button>
            ) : null}
            <button type="button" className="button" onClick={decline}>
              {unusable || wrongAccount ? "Dismiss" : "Not now"}
            </button>
          </div>
        </div>
      ) : notFound ? (
        <div className="card stack">
          <p className="notice notice-error" role="alert">
            This invitation link isn&apos;t valid. Check you copied the whole link.
          </p>
          <button type="button" className="button" onClick={decline}>
            Dismiss
          </button>
        </div>
      ) : (
        <ErrorNotice error={error} />
      )}
    </div>
  );
}
