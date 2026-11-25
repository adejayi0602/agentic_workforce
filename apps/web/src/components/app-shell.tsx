"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { useSession } from "@/lib/session";

interface NavItem {
  href: string;
  label: string;
  permission?: string;
  sprint?: number;
}

const NAV: NavItem[] = [
  { href: "/", label: "Overview" },
  { href: "/projects", label: "Projects", permission: "project.read" },
  { href: "/members", label: "Members", permission: "members.read" },
  { href: "/audit", label: "Audit", permission: "audit.read" },
  { href: "/manifests", label: "Manifest Studio", sprint: 5 },
  { href: "/approvals", label: "Approvals", sprint: 9 },
];

function isActive(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const session = useSession();
  const pathname = usePathname();
  const router = useRouter();

  if (session.status === "signed-out") {
    return <main className="content content-bare">{children}</main>;
  }

  const memberships = session.me?.memberships ?? [];
  const visibleNav = NAV.filter((item) => !item.permission || session.can(item.permission));

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">Agentic Workforce</div>

        {memberships.length > 0 ? (
          <label className="org-switcher">
            <span className="small muted">Organisation</span>
            <select
              value={session.organisationId ?? ""}
              onChange={(event) => {
                if (event.target.value === "__new") router.push("/organisations/new");
                else session.selectOrganisation(event.target.value);
              }}
            >
              {memberships.map((m) => (
                <option key={m.organisation_id} value={m.organisation_id}>
                  {m.name}
                </option>
              ))}
              <option value="__new">+ New organisation…</option>
            </select>
          </label>
        ) : null}

        <nav aria-label="Main">
          <ul>
            {visibleNav.map((item) => (
              <li key={item.href}>
                {item.sprint ? (
                  <span className="nav-disabled" title={`Arrives in Sprint ${item.sprint}`}>
                    {item.label}
                    <small>Sprint {item.sprint}</small>
                  </span>
                ) : (
                  <Link
                    href={item.href}
                    aria-current={isActive(pathname, item.href) ? "page" : undefined}
                  >
                    {item.label}
                  </Link>
                )}
              </li>
            ))}
          </ul>
        </nav>

        {session.me ? (
          <div className="account">
            <p className="small">
              <strong>{session.me.display_name ?? session.me.email ?? "Signed in"}</strong>
              {session.membership ? (
                <span className="muted"> · {session.membership.role.replace("_", " ")}</span>
              ) : null}
            </p>
            <button type="button" className="link-button" onClick={session.signOut}>
              Sign out
            </button>
          </div>
        ) : null}
      </aside>
      <main className="content">{children}</main>
    </div>
  );
}
