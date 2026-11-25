"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { ErrorNotice } from "@/components/error-notice";
import { useSession } from "@/lib/session";

/**
 * Renders children once the user is signed in and has an organisation selected.
 * Signed-out visitors go to /sign-in. Users with no organisation are offered to create one.
 */
export function RequireSession({
  children,
  needsOrganisation = true,
}: {
  children: React.ReactNode;
  needsOrganisation?: boolean;
}) {
  const session = useSession();
  const router = useRouter();

  useEffect(() => {
    if (session.status === "signed-out") router.replace("/sign-in");
  }, [session.status, router]);

  if (session.status === "signed-out" || session.status === "loading") {
    return <p role="status">Loading…</p>;
  }
  if (session.status === "error") {
    return (
      <>
        <ErrorNotice error={session.error} />
        <button type="button" className="button" onClick={() => void session.refresh()}>
          Try again
        </button>
      </>
    );
  }
  if (needsOrganisation && !session.organisationId) {
    return (
      <div className="card">
        <h2>No organisation yet</h2>
        <p>You aren&apos;t a member of any organisation. Create one to start a project.</p>
        <Link className="button button-primary" href="/organisations/new">
          Create an organisation
        </Link>
      </div>
    );
  }
  return <>{children}</>;
}
