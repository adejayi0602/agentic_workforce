import { ApiError, describeError } from "@/lib/api";

/** An error as a sentence, plus the correlation ID support needs to find it in the logs. */
export function ErrorNotice({ error }: { error: unknown }) {
  if (!error) return null;
  const correlationId = error instanceof ApiError ? error.correlationId : undefined;
  return (
    <div className="notice notice-error" role="alert">
      <p>{describeError(error)}</p>
      {correlationId ? <p className="muted small">Correlation ID: {correlationId}</p> : null}
    </div>
  );
}
