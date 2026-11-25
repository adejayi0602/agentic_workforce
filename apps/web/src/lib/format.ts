export function formatDate(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function humanise(value: string): string {
  const words = value.replace(/[._]/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}
