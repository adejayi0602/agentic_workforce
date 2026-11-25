"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ErrorNotice } from "@/components/error-notice";
import { RequireSession } from "@/components/require-session";
import { apiRequest, type Project, type ProjectCreate } from "@/lib/api";
import { useSession } from "@/lib/session";

const TYPES: ProjectCreate["type"][] = ["software", "infrastructure", "data", "operations", "other"];

export default function NewProjectPage() {
  return (
    <RequireSession>
      <NewProjectForm />
    </RequireSession>
  );
}

function NewProjectForm() {
  const { token, organisationId, can } = useSession();
  const router = useRouter();
  const [form, setForm] = useState({ key: "", name: "", description: "", type: "software" as ProjectCreate["type"] });
  // One key per form. A double click, or a retry after a network error, can't create twice.
  const [idempotencyKey] = useState(() => `web-${crypto.randomUUID()}`);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  if (!can("project.create")) {
    return (
      <div className="card">
        <h1>New project</h1>
        <p>Your role can&apos;t create projects. Ask an org admin or project owner.</p>
      </div>
    );
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body: ProjectCreate = {
        key: form.key,
        name: form.name.trim(),
        type: form.type,
        description: form.description.trim() || null,
      };
      const project = await apiRequest<Project>("POST", "/api/v1/projects", {
        token,
        organisationId,
        body,
        idempotencyKey,
      });
      router.push(`/projects/${project.id}`);
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  return (
    <>
      <h1>New project</h1>
      <form className="card form" onSubmit={(e) => void submit(e)}>
        <label>
          Name
          <input
            required
            maxLength={200}
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
        </label>
        <label>
          Key
          <input
            required
            pattern="[A-Z][A-Z0-9]{1,9}"
            title="2–10 characters: a capital letter, then capitals or digits"
            value={form.key}
            onChange={(e) => setForm({ ...form, key: e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, "") })}
            placeholder="PAY"
            aria-describedby="project-key-hint"
          />
        </label>
        <p id="project-key-hint" className="hint small muted">
          Prefixes requirement and task IDs, like REQ-PAY-014. It can&apos;t be changed later.
        </p>
        <label>
          Type
          <select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value as ProjectCreate["type"] })}>
            {TYPES.map((t) => (
              <option key={t} value={t}>
                {t[0].toUpperCase() + t.slice(1)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Description <span className="muted">(optional)</span>
          <textarea
            rows={4}
            maxLength={5000}
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
          />
        </label>
        <ErrorNotice error={error} />
        <button type="submit" className="button button-primary" disabled={busy}>
          {busy ? "Creating…" : "Create project"}
        </button>
      </form>
    </>
  );
}
