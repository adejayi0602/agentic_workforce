"use client";

import Link from "next/link";

import { ApiStatus } from "@/components/api-status";
import { RequireSession } from "@/components/require-session";
import { useSession } from "@/lib/session";

export default function OverviewPage() {
  return (
    <RequireSession>
      <Overview />
    </RequireSession>
  );
}

function Overview() {
  const { organisation, can } = useSession();
  if (!organisation) return null;

  return (
    <>
      <h1>{organisation.name}</h1>
      <p className="lede">
        You&apos;re signed in as <strong>{organisation.your_role.replace("_", " ")}</strong>.
      </p>

      <div className="grid">
        <section className="card" aria-labelledby="next-steps">
          <h2 id="next-steps">Get started</h2>
          <ul className="plain">
            <li>
              <Link href="/projects">View projects</Link>
            </li>
            {can("project.create") ? (
              <li>
                <Link href="/projects/new">Create a project</Link>
              </li>
            ) : null}
            <li>
              <Link href="/members">See who&apos;s in this organisation</Link>
            </li>
            {can("audit.read") ? (
              <li>
                <Link href="/audit">Review the audit trail</Link>
              </li>
            ) : null}
          </ul>
        </section>

        <section className="card" aria-labelledby="platform-status">
          <h2 id="platform-status">Platform status</h2>
          <ApiStatus />
        </section>
      </div>

      <section className="card" aria-labelledby="permissions">
        <h2 id="permissions">What your role can do</h2>
        <ul className="tags">
          {organisation.your_permissions.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      </section>
    </>
  );
}
