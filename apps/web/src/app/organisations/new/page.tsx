"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ErrorNotice } from "@/components/error-notice";
import { RequireSession } from "@/components/require-session";
import { apiRequest, type Organisation } from "@/lib/api";
import { useSession } from "@/lib/session";

function slugify(name: string): string {
  return name
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 63);
}

export default function NewOrganisationPage() {
  return (
    <RequireSession needsOrganisation={false}>
      <NewOrganisationForm />
    </RequireSession>
  );
}

function NewOrganisationForm() {
  const session = useSession();
  const router = useRouter();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugEdited, setSlugEdited] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const org = await apiRequest<Organisation>("POST", "/api/v1/organisations", {
        token: session.token,
        body: { name: name.trim(), slug },
      });
      session.selectOrganisation(org.id);
      await session.refresh();
      router.push("/");
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  return (
    <>
      <h1>New organisation</h1>
      <p className="lede">You&apos;ll be its first org admin.</p>
      <form className="card form" onSubmit={(e) => void submit(e)}>
        <label>
          Name
          <input
            required
            maxLength={200}
            value={name}
            onChange={(e) => {
              setName(e.target.value);
              if (!slugEdited) setSlug(slugify(e.target.value));
            }}
          />
        </label>
        <label>
          Short name for links
          <input
            required
            pattern={"[a-z0-9][a-z0-9\\-]{1,61}[a-z0-9]"}
            title="3–63 lowercase letters, numbers or hyphens"
            value={slug}
            onChange={(e) => {
              setSlug(e.target.value);
              setSlugEdited(true);
            }}
            aria-describedby="org-slug-hint"
          />
        </label>
        <p id="org-slug-hint" className="hint small muted">
          Lowercase letters, numbers and hyphens.
        </p>
        <ErrorNotice error={error} />
        <button type="submit" className="button button-primary" disabled={busy}>
          {busy ? "Creating…" : "Create organisation"}
        </button>
      </form>
    </>
  );
}
