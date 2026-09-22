import { afterEach, expect, rs, test } from "@rstest/core";

import { fetchRunMessagesPage } from "@/core/threads/history-page";

afterEach(() => {
  rs.unstubAllGlobals();
});

test("an HTTP error cannot masquerade as an empty terminal history page", async () => {
  rs.stubGlobal(
    "fetch",
    rs.fn(
      async () =>
        new Response(
          JSON.stringify({
            data: [],
            has_more: false,
            detail: "private server traceback",
          }),
          { status: 500 },
        ),
    ),
  );
  await expect(
    fetchRunMessagesPage("/api/threads/thread/runs/run/messages"),
  ).rejects.toThrow("HTTP 500");
});

test("retrying a failed history page preserves its requested cursor and accepts an empty terminal page", async () => {
  const fetchFn = rs
    .fn()
    .mockResolvedValueOnce(new Response("{}", { status: 503 }))
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ data: [], has_more: false })),
    );
  rs.stubGlobal("fetch", fetchFn);
  const url = "/api/threads/thread/runs/run/messages?before_seq=27";
  await expect(fetchRunMessagesPage(url)).rejects.toThrow("HTTP 503");
  await expect(fetchRunMessagesPage(url)).resolves.toEqual({
    data: [],
    has_more: false,
  });
  expect(fetchFn.mock.calls.map((args) => args[0])).toEqual([url, url]);
});

test("cancelled history responses cannot be consumed after a thread switch", async () => {
  const controller = new AbortController();
  let resolveResponse!: (response: Response) => void;
  const fetchFn = rs.fn(
    (_url: string, _init?: RequestInit) =>
      new Promise<Response>((resolve) => {
        resolveResponse = resolve;
      }),
  );
  rs.stubGlobal("fetch", fetchFn);
  const request = fetchRunMessagesPage(
    "/api/threads/old/runs/run/messages",
    controller.signal,
  );
  controller.abort();
  resolveResponse(new Response(JSON.stringify({ data: [], has_more: false })));
  await expect(request).rejects.toMatchObject({ name: "AbortError" });
  expect(fetchFn.mock.calls[0]?.[1]?.signal).toBe(controller.signal);
});

test("malformed history JSON is rejected instead of being consumed as a page", async () => {
  rs.stubGlobal(
    "fetch",
    rs.fn(
      async () =>
        new Response(JSON.stringify({ detail: "private configuration" }), {
          status: 200,
        }),
    ),
  );
  await expect(
    fetchRunMessagesPage("/api/threads/thread/runs/run/messages"),
  ).rejects.toThrow("Invalid thread history response");
});
