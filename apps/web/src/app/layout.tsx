import type { Metadata } from "next";
import { Suspense } from "react";

import { AppShell } from "@/components/app-shell";
import { SessionProvider } from "@/lib/session";
import "./globals.css";

export const metadata: Metadata = {
  title: "Agentic Workforce",
  description: "Manifest-driven, multi-agent IT project delivery",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en">
      <body>
        {/* The session reads browser storage, so it renders only in the browser. */}
        <Suspense fallback={<p className="content">Loading…</p>}>
          <SessionProvider>
            <AppShell>{children}</AppShell>
          </SessionProvider>
        </Suspense>
      </body>
    </html>
  );
}
