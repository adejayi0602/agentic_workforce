import { describeStatus } from "@/lib/documents";

export function StatusPill({ status }: { status: string }) {
  const { label, tone } = describeStatus(status);
  return <span className={`pill pill-tone-${tone}`}>{label}</span>;
}
