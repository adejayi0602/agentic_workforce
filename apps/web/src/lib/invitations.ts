import { read, write } from "./storage";

/**
 * An invitation link carries its token in the URL fragment (`#token=...`). Browsers never send
 * fragments to servers, so the token stays out of logs. Until the person accepts, the token is
 * held for this tab only, so it survives the trip through sign-in.
 */
const KEY = "workforce.invitation_token";
export const ACCEPT_PATH = "/invitations/accept";

export function tokenFromHash(hash: string): string | null {
  const params = new URLSearchParams(hash.replace(/^#/, ""));
  const token = params.get("token")?.trim();
  return token && token.length >= 20 ? token : null;
}

export function rememberInvitation(token: string): void {
  write("session", KEY, token);
}

export function pendingInvitation(): string | null {
  return read("session", KEY);
}

export function forgetInvitation(): void {
  write("session", KEY, null);
}

/** Where to go once signed in: back to the invitation if one is waiting. */
export function afterSignInPath(): string {
  return pendingInvitation() ? ACCEPT_PATH : "/";
}

export function describeInvitationStatus(status: string): { label: string; tone: "ok" | "bad" | "busy" | "neutral" } {
  switch (status) {
    case "pending":
      return { label: "Waiting", tone: "busy" };
    case "accepted":
      return { label: "Accepted", tone: "ok" };
    case "revoked":
      return { label: "Revoked", tone: "neutral" };
    case "expired":
      return { label: "Expired", tone: "bad" };
    default:
      return { label: status, tone: "neutral" };
  }
}
