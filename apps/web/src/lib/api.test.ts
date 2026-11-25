import { describe, expect, it } from "vitest";

import { ApiError, describeError, toApiError } from "./api";

describe("toApiError", () => {
  it("reads the spec §6.2 envelope", async () => {
    const response = new Response(
      JSON.stringify({
        error: { code: "FORBIDDEN", message: "No.", correlation_id: "c-1", details: { permission: "x" } },
      }),
      { status: 403 },
    );
    const err = await toApiError(response);
    expect(err.status).toBe(403);
    expect(err.code).toBe("FORBIDDEN");
    expect(err.correlationId).toBe("c-1");
    expect(describeError(err)).toBe("No.");
  });

  it("tolerates bodies that aren't the envelope", async () => {
    const err = await toApiError(new Response("<html>bad gateway</html>", { status: 502 }));
    expect(err.status).toBe(502);
    expect(err.body).toBeNull();
    expect(describeError(err)).toBe("Request failed (502).");
  });
});

describe("describeError", () => {
  it("explains an unreachable API", () => {
    expect(describeError(new ApiError(0, null))).toMatch(/not reachable/);
  });

  it("never exposes unknown errors", () => {
    expect(describeError(new Error("stack trace here"))).toBe("Something went wrong.");
  });
});
