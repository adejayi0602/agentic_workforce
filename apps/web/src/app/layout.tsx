import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Agentic Workforce",
  description: "Manifest-driven, multi-agent IT project delivery",
};

const NAV = [
  { href: "/", label: "Overview" },
  { href: "/projects", label: "Projects", sprint: 1 },
  { href: "/manifests", label: "Manifest Studio", sprint: 5 },
  { href: "/approvals", label: "Approvals", sprint: 9 },
  { href: "/audit", label: "Audit", sprint: 9 },
];

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en">
      <body>
        <div className="shell">
          <aside className="sidebar">
            <div className="brand">Agentic Workforce</div>
            <nav aria-label="Main">
              <ul>
                {NAV.map((item) => (
                  <li key={item.href}>
                    {item.sprint ? (
                      <span className="nav-disabled" title={`Arrives in Sprint ${item.sprint}`}>
                        {item.label}
                        <small>Sprint {item.sprint}</small>
                      </span>
                    ) : (
                      <Link href={item.href}>{item.label}</Link>
                    )}
                  </li>
                ))}
              </ul>
            </nav>
          </aside>
          <main className="content">{children}</main>
        </div>
      </body>
    </html>
  );
}
