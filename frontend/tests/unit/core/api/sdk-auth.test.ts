import { afterEach, expect, rs, test } from "@rstest/core";

rs.mock("@/core/config", () => ({
  getLangGraphBaseURL: () => "http://gateway.test:8001/api/langgraph",
}));

import { authorizeSdkRequest, getAPIClient } from "@/core/api/api-client";

afterEach(() => {
  rs.unstubAllGlobals();
});

test("SDK requests include the session cookie for the configured split-origin backend", async () => {
  rs.stubGlobal("window", {
    location: { origin: "http://frontend.test:3000" },
  });
  rs.stubGlobal("document", { cookie: "csrf_token=rotated-csrf" });
  const fetchFn = rs.fn(async () => new Response("[]", { status: 200 }));
  rs.stubGlobal("fetch", fetchFn);
  await getAPIClient(false, "auth-regression").threads.search({ limit: 1 });
  const [url, init] = fetchFn.mock.calls[0] as unknown as [string, RequestInit];
  expect(url).toBe("http://gateway.test:8001/api/langgraph/threads/search");
  expect(init.credentials).toBe("include");
  expect(new Headers(init.headers).get("X-CSRF-Token")).toBe("rotated-csrf");
});

test("SDK auth defaults stay inside the configured backend origin and path", () => {
  rs.stubGlobal("document", { cookie: "csrf_token=private-csrf" });
  const configured = "http://gateway.test:8001/api/langgraph";
  const init: RequestInit = { method: "POST" };
  for (const url of [
    "http://elsewhere.test/api/langgraph/threads",
    "http://gateway.test:8001/api/langgraph-other/threads",
    "http://gateway.test:9000/api/langgraph/threads",
  ]) {
    expect(authorizeSdkRequest(new URL(url), init, configured)).toBe(init);
  }
});

test("SDK auth honors explicit cookie policies and CSRF overrides without mutating caller headers", () => {
  rs.stubGlobal("window", {
    location: { origin: "http://frontend.test:3000" },
  });
  rs.stubGlobal("document", { cookie: "csrf_token=ambient-token" });
  const configured = "http://gateway.test:8001/api/langgraph";
  const url = new URL(`${configured}/threads/search`);
  for (const credentials of ["omit", "same-origin"] as const) {
    const prepared = authorizeSdkRequest(
      url,
      { method: "POST", credentials },
      configured,
    );
    expect(prepared.credentials).toBe(credentials);
    expect(new Headers(prepared.headers).has("X-CSRF-Token")).toBe(false);
  }
  const headers = new Headers({ "X-CSRF-Token": "explicit-token" });
  const prepared = authorizeSdkRequest(
    url,
    { method: "POST", headers },
    configured,
  );
  expect(new Headers(prepared.headers).get("X-CSRF-Token")).toBe(
    "explicit-token",
  );
  expect(headers.get("X-CSRF-Token")).toBe("explicit-token");
  const safe = authorizeSdkRequest(url, { method: "GET" }, configured);
  expect(safe.credentials).toBe("include");
  expect(new Headers(safe.headers).has("X-CSRF-Token")).toBe(false);
});

test("SDK streaming requests include credentials and read the current CSRF cookie each time", async () => {
  rs.stubGlobal("document", { cookie: "csrf_token=first" });
  const fetchFn = rs.fn(
    async (_url: unknown, _init?: RequestInit) =>
      new Response("event: end\ndata: {}\n\n", {
        headers: { "Content-Type": "text/event-stream" },
      }),
  );
  rs.stubGlobal("fetch", fetchFn);
  for (const token of ["first", "rotated"]) {
    rs.stubGlobal("document", { cookie: `csrf_token=${token}` });
    for await (const event of getAPIClient(false, "stream-auth").runs.stream(
      null,
      "lead_agent",
      { input: {} },
    )) {
      expect(event).toHaveProperty("event");
    }
    const init = fetchFn.mock.calls.at(-1)?.[1];
    expect(init?.credentials).toBe("include");
    expect(new Headers(init?.headers).get("X-CSRF-Token")).toBe(token);
  }
});
