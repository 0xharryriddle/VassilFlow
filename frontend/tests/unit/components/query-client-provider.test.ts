import { afterEach, expect, rs, test } from "@rstest/core";
import { type QueryClient, useQueryClient } from "@tanstack/react-query";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: rs.fn(() => ({ user: { id: "account-a" } })),
}));

import { QueryClientProvider } from "@/components/query-client-provider";
import { useAuth } from "@/core/auth/AuthProvider";

const clients: QueryClient[] = [];
afterEach(() => {
  clients.forEach((client) => client.clear());
  clients.length = 0;
});

function MemoryProbe() {
  const client = useQueryClient();
  clients.push(client);
  return createElement(
    "output",
    null,
    client.getQueryData<string>(["memory"]) ?? "empty",
  );
}

test("a fresh workspace cannot reuse private data from a previous account", () => {
  renderToStaticMarkup(
    createElement(QueryClientProvider, null, createElement(MemoryProbe)),
  );
  clients[0]!.setQueryData(["memory"], "account-a private facts");
  rs.mocked(useAuth).mockReturnValue({
    user: { id: "account-b" },
  } as ReturnType<typeof useAuth>);
  const nextAccount = renderToStaticMarkup(
    createElement(QueryClientProvider, null, createElement(MemoryProbe)),
  );
  expect(clients[1]).not.toBe(clients[0]);
  expect(nextAccount).toBe("<output>empty</output>");
});
