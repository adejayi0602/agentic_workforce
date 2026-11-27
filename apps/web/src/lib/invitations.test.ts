import { afterEach, describe, expect, it } from "vitest";

import {
  ACCEPT_PATH,
  afterSignInPath,
  describeInvitationStatus,
  forgetInvitation,
  pendingInvitation,
  rememberInvitation,
  tokenFromHash,
} from "./invitations";

const TOKEN = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789-_xyz";

describe("tokenFromHash", () => {
  it("reads the token from the fragment", () => {
    expect(tokenFromHash(`#token=${TOKEN}`)).toBe(TOKEN);
    expect(tokenFromHash(`token=${TOKEN}`)).toBe(TOKEN);
  });

  it("ignores missing or implausible tokens", () => {
    expect(tokenFromHash("")).toBeNull();
    expect(tokenFromHash("#token=short")).toBeNull();
    expect(tokenFromHash("#other=1")).toBeNull();
  });
});

describe("pending invitation", () => {
  afterEach(() => forgetInvitation());

  it("sends people back to the invitation after sign-in", () => {
    expect(afterSignInPath()).toBe("/");
    rememberInvitation(TOKEN);
    expect(pendingInvitation()).toBe(TOKEN);
    expect(afterSignInPath()).toBe(ACCEPT_PATH);
    forgetInvitation();
    expect(afterSignInPath()).toBe("/");
  });
});

describe("describeInvitationStatus", () => {
  it("labels each status", () => {
    expect(describeInvitationStatus("pending").label).toBe("Waiting");
    expect(describeInvitationStatus("expired").tone).toBe("bad");
    expect(describeInvitationStatus("accepted").tone).toBe("ok");
  });
});
