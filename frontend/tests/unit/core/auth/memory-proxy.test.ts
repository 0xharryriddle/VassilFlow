import { afterEach, expect, rs, test } from "@rstest/core";
import { type NextRequest } from "next/server";

rs.mock("@/core/auth/gateway-config", () => ({
  getGatewayConfig: () => ({
    internalGatewayUrl: "http://private-gateway:8001",
    trustedOrigins: [],
  }),
}));

import { PATCH, POST, GET as GET_PATH } from "@/app/api/memory/[...path]/route";
import { DELETE, GET } from "@/app/api/memory/route";

afterEach(() => {
  rs.unstubAllGlobals();
});

test.each([GET, DELETE])(
  "root memory routes use the private Gateway URL",
  async (handler) => {
    const transport = rs.fn(
      async () => new Response('{"facts":[]}', { status: 200 }),
    );
    rs.stubGlobal("fetch", transport);
    const method = handler === GET ? "GET" : "DELETE";
    const response = await handler(
      new Request("http://frontend.test/api/memory", {
        method,
        headers: {
          cookie: "access_token=fixture",
          "x-csrf-token": "csrf-fixture",
          host: "frontend.test",
        },
      }) as NextRequest,
    );
    const [url, init] = transport.mock.calls[0] as unknown as [
      URL,
      RequestInit,
    ];
    expect(String(url)).toBe("http://private-gateway:8001/api/memory");
    expect(init.method).toBe(method);
    expect(new Headers(init.headers).get("cookie")).toBe(
      "access_token=fixture",
    );
    expect(new Headers(init.headers).get("x-csrf-token")).toBe("csrf-fixture");
    expect(new Headers(init.headers).has("host")).toBe(false);
    expect(await response.json()).toEqual({ facts: [] });
  },
);

test.each([PATCH, POST, GET_PATH])(
  "nested memory routes share the resolver and forward requests",
  async (handler) => {
    const transport = rs.fn(
      async () => new Response("upstream failure", { status: 409 }),
    );
    rs.stubGlobal("fetch", transport);
    const method =
      handler === GET_PATH ? "GET" : handler === PATCH ? "PATCH" : "POST";
    const request = new Request("http://frontend.test/api/memory/facts/item", {
      method,
      ...(method === "GET" ? {} : { body: '{"text":"updated"}' }),
    }) as NextRequest;
    const response = await handler(request, {
      params: Promise.resolve({ path: ["facts", "item"] }),
    });
    const [url, init] = transport.mock.calls[0] as unknown as [
      URL,
      RequestInit,
    ];
    expect(String(url)).toBe(
      "http://private-gateway:8001/api/memory/facts/item",
    );
    expect(init.method).toBe(method);
    if (method !== "GET")
      expect(new TextDecoder().decode(init.body as ArrayBuffer)).toBe(
        '{"text":"updated"}',
      );
    expect(response.status).toBe(409);
  },
);
