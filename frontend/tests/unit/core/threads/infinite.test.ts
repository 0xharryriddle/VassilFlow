import { describe, expect, rs, test } from "@rstest/core";
import {
  InfiniteQueryObserver,
  QueryClient,
  type InfiniteData,
} from "@tanstack/react-query";

import { SIDECAR_METADATA_KEY } from "@/core/sidecar/thread";
import {
  fetchInfiniteThreadsPage,
  filterInfiniteThreadsCache,
  getInfiniteThreadsNextPageParam,
  INFINITE_THREADS_PAGE_SIZE,
  INFINITE_THREADS_QUERY_KEY_PREFIX,
  type InfiniteThreadsPage,
  mapInfiniteThreadsCache,
  upsertThreadInInfiniteCache,
} from "@/core/threads/hooks";
import type { AgentThread } from "@/core/threads/types";

// Issue #3482: the sidebar and /workspace/chats list used to be capped at
// 50 threads because `useThreads()` exits as soon as `threads.length >=
// params.limit`.  These pure helpers back the `useInfiniteThreads()`
// pagination logic and the mirrored cache writes that keep rename / delete
// / stream-finish in sync with both the legacy array cache and the new
// infinite cache.

function makeThread(
  id: string,
  title = `Title ${id}`,
  metadata: Record<string, unknown> = {},
): AgentThread {
  return {
    thread_id: id,
    created_at: "2025-01-01T00:00:00Z",
    updated_at: "2025-01-01T00:00:00Z",
    metadata,
    status: "idle",
    values: { title },
  } as unknown as AgentThread;
}

function makePage(
  start: number,
  size: number,
  pageSize = INFINITE_THREADS_PAGE_SIZE,
): InfiniteThreadsPage {
  return {
    threads: Array.from({ length: size }, (_, i) =>
      makeThread(`t-${start + i}`),
    ),
    nextOffset: size === pageSize ? start + size : null,
  };
}

function makeInfiniteData(
  pages: AgentThread[][],
): InfiniteData<InfiniteThreadsPage> {
  return {
    pages: pages.map((threads, i) => ({
      threads,
      nextOffset:
        threads.length === INFINITE_THREADS_PAGE_SIZE
          ? (i + 1) * INFINITE_THREADS_PAGE_SIZE
          : null,
    })),
    pageParams: pages.map((_, i) => i * INFINITE_THREADS_PAGE_SIZE),
  };
}

describe("getInfiniteThreadsNextPageParam", () => {
  test("returns next offset when the last page is full", () => {
    const page1 = makePage(0, INFINITE_THREADS_PAGE_SIZE);
    expect(getInfiniteThreadsNextPageParam(page1)).toBe(
      INFINITE_THREADS_PAGE_SIZE,
    );
  });

  test("returns next offset across multiple full pages", () => {
    const page2 = makePage(
      INFINITE_THREADS_PAGE_SIZE,
      INFINITE_THREADS_PAGE_SIZE,
    );
    expect(getInfiniteThreadsNextPageParam(page2)).toBe(
      INFINITE_THREADS_PAGE_SIZE * 2,
    );
  });

  test("returns undefined when the last page is short (end of list)", () => {
    const page2 = makePage(INFINITE_THREADS_PAGE_SIZE, 10);
    expect(getInfiniteThreadsNextPageParam(page2)).toBeUndefined();
  });

  test("returns undefined when the last page is empty", () => {
    expect(
      getInfiniteThreadsNextPageParam({ threads: [], nextOffset: null }),
    ).toBeUndefined();
  });

  test("respects a custom page size", () => {
    const page1 = makePage(0, 5, 5);
    expect(getInfiniteThreadsNextPageParam(page1)).toBe(5);
    expect(getInfiniteThreadsNextPageParam(makePage(0, 5, 10))).toBeUndefined();
  });
});

describe("fetchInfiniteThreadsPage", () => {
  test("TanStack fetchNextPage uses the raw cursor after filtering every cached visible row", async () => {
    const client = new QueryClient();
    const key = [...INFINITE_THREADS_QUERY_KEY_PREFIX, {}];
    const search = rs
      .fn()
      .mockResolvedValueOnce([
        makeThread("sidecar", "Sidecar", { [SIDECAR_METADATA_KEY]: true }),
        makeThread("primary-1"),
      ])
      .mockResolvedValueOnce([makeThread("primary-2")])
      .mockResolvedValueOnce([]);
    const observer = new InfiniteQueryObserver(client, {
      queryKey: key,
      initialPageParam: 0,
      queryFn: ({ pageParam }) =>
        fetchInfiniteThreadsPage({ threads: { search } }, {}, pageParam, 2),
      getNextPageParam: getInfiniteThreadsNextPageParam,
      retry: false,
    });
    try {
      await observer.refetch();
      client.setQueryData<InfiniteData<InfiniteThreadsPage>>(key, (data) =>
        filterInfiniteThreadsCache(data, () => false),
      );
      const result = await observer.fetchNextPage();
      expect(search).toHaveBeenLastCalledWith({ offset: 3, limit: 2 });
      expect(result.data?.pageParams).toEqual([0, 3]);
      expect(result.hasNextPage).toBe(false);
      expect(result.data?.pages[1]).toEqual({ threads: [], nextOffset: null });
    } finally {
      observer.destroy();
      client.clear();
    }
  });

  test("refetch structural sharing retains a changed cursor even when visible rows are identical", () => {
    const client = new QueryClient();
    const key = [...INFINITE_THREADS_QUERY_KEY_PREFIX, {}];
    client.setQueryData(key, {
      pages: [{ threads: [makeThread("same")], nextOffset: 2 }],
      pageParams: [0],
    });
    client.setQueryData(key, {
      pages: [{ threads: [makeThread("same")], nextOffset: 3 }],
      pageParams: [0],
    });
    expect(
      client.getQueryData<InfiniteData<InfiniteThreadsPage>>(key)?.pages[0]
        ?.nextOffset,
    ).toBe(3);
  });

  test("retains the raw cursor after QueryClient structural sharing and cache mutations", async () => {
    const client = new QueryClient();
    const key = [...INFINITE_THREADS_QUERY_KEY_PREFIX, {}];
    const search = rs
      .fn()
      .mockResolvedValueOnce([
        makeThread("sidecar", "Sidecar", { [SIDECAR_METADATA_KEY]: true }),
        makeThread("primary-1"),
      ])
      .mockResolvedValueOnce([makeThread("primary-2")]);
    const page = await fetchInfiniteThreadsPage(
      { threads: { search } },
      {},
      0,
      2,
    );
    client.setQueryData(key, { pages: [page], pageParams: [0] });
    client.setQueryData<InfiniteData<InfiniteThreadsPage>>(key, (data) =>
      mapInfiniteThreadsCache(data, (thread) => ({
        ...thread,
        status: "busy",
      })),
    );
    const updated =
      client.getQueryData<InfiniteData<InfiniteThreadsPage>>(key)!;
    expect(getInfiniteThreadsNextPageParam(updated.pages[0]!)).toBe(3);
    client.setQueryData<InfiniteData<InfiniteThreadsPage>>(key, (data) =>
      filterInfiniteThreadsCache(
        data,
        (thread) => thread.thread_id !== "primary-1",
      ),
    );
    const filtered =
      client.getQueryData<InfiniteData<InfiniteThreadsPage>>(key)!;
    expect(getInfiniteThreadsNextPageParam(filtered.pages[0]!)).toBe(3);
  });

  test("an optimistic insertion into a terminal page does not invent another backend page", async () => {
    const client = new QueryClient();
    const key = [...INFINITE_THREADS_QUERY_KEY_PREFIX, {}];
    const search = rs.fn().mockResolvedValueOnce([makeThread("only")]);
    const page = await fetchInfiniteThreadsPage(
      { threads: { search } },
      {},
      0,
      2,
    );
    client.setQueryData(key, { pages: [page], pageParams: [0] });
    upsertThreadInInfiniteCache(client, makeThread("new"));
    const updated =
      client.getQueryData<InfiniteData<InfiniteThreadsPage>>(key)!;
    expect(getInfiniteThreadsNextPageParam(updated.pages[0]!)).toBeUndefined();
  });

  test("fills a visible page while advancing offsets by raw backend rows", async () => {
    const search = rs
      .fn()
      .mockResolvedValueOnce([
        makeThread("sidecar-1", "Sidecar", { [SIDECAR_METADATA_KEY]: true }),
        makeThread("primary-1"),
      ])
      .mockResolvedValueOnce([makeThread("primary-2")]);

    const page = await fetchInfiniteThreadsPage(
      { threads: { search } },
      { sortBy: "updated_at", sortOrder: "desc" },
      0,
      2,
    );

    expect(page.threads.map((thread) => thread.thread_id)).toEqual([
      "primary-1",
      "primary-2",
    ]);
    expect(search).toHaveBeenNthCalledWith(1, {
      sortBy: "updated_at",
      sortOrder: "desc",
      limit: 2,
      offset: 0,
    });
    expect(search).toHaveBeenNthCalledWith(2, {
      sortBy: "updated_at",
      sortOrder: "desc",
      limit: 1,
      offset: 2,
    });
    expect(getInfiniteThreadsNextPageParam(page)).toBe(3);
  });

  test("keeps sidecar rows when the caller explicitly searches for sidecars", async () => {
    const search = rs.fn().mockResolvedValueOnce([
      makeThread("sidecar-1", "Sidecar", {
        [SIDECAR_METADATA_KEY]: true,
        parent_thread_id: "parent-1",
      }),
    ]);

    const page = await fetchInfiniteThreadsPage(
      { threads: { search } },
      {
        sortBy: "updated_at",
        sortOrder: "desc",
        metadata: {
          [SIDECAR_METADATA_KEY]: true,
          parent_thread_id: "parent-1",
        },
      },
      0,
      2,
    );

    expect(page.threads.map((thread) => thread.thread_id)).toEqual([
      "sidecar-1",
    ]);
    expect(getInfiniteThreadsNextPageParam(page)).toBeUndefined();
  });
});

describe("mapInfiniteThreadsCache", () => {
  test("returns undefined when oldData is undefined", () => {
    expect(mapInfiniteThreadsCache(undefined, (t) => t)).toBeUndefined();
  });

  test("updates the matching thread across multiple pages", () => {
    const page1 = [makeThread("a"), makeThread("b")];
    const page2 = [makeThread("c"), makeThread("d")];
    const data = makeInfiniteData([page1, page2]);

    const updated = mapInfiniteThreadsCache(data, (t) =>
      t.thread_id === "c"
        ? { ...t, values: { ...t.values, title: "renamed" } }
        : t,
    );

    expect(updated?.pages[0]?.threads[0]?.values?.title).toBe("Title a");
    expect(updated?.pages[1]?.threads[0]?.thread_id).toBe("c");
    expect(updated?.pages[1]?.threads[0]?.values?.title).toBe("renamed");
    expect(updated?.pages[1]?.threads[1]?.values?.title).toBe("Title d");
  });

  test("preserves pageParams", () => {
    const data = makeInfiniteData([[makeThread("a")]]);
    const updated = mapInfiniteThreadsCache(data, (t) => t);
    expect(updated?.pageParams).toEqual(data.pageParams);
  });
});

describe("filterInfiniteThreadsCache", () => {
  test("returns undefined when oldData is undefined", () => {
    expect(filterInfiniteThreadsCache(undefined, () => true)).toBeUndefined();
  });

  test("removes matching threads across all pages", () => {
    const page1 = [makeThread("a"), makeThread("b")];
    const page2 = [makeThread("b"), makeThread("c")];
    const data = makeInfiniteData([page1, page2]);

    const filtered = filterInfiniteThreadsCache(
      data,
      (t) => t.thread_id !== "b",
    );

    expect(filtered?.pages[0]?.threads.map((t) => t.thread_id)).toEqual(["a"]);
    expect(filtered?.pages[1]?.threads.map((t) => t.thread_id)).toEqual(["c"]);
  });

  test("keeps an emptied page as an empty array (does not drop the page)", () => {
    const page1 = [makeThread("a")];
    const page2 = [makeThread("b")];
    const data = makeInfiniteData([page1, page2]);

    const filtered = filterInfiniteThreadsCache(
      data,
      (t) => t.thread_id !== "a",
    );

    expect(filtered?.pages).toHaveLength(2);
    expect(filtered?.pages[0]?.threads).toEqual([]);
    expect(filtered?.pages[1]?.threads[0]?.thread_id).toBe("b");
  });

  test("does not regress next offset when an earlier page has been shrunk by a delete", () => {
    const data = {
      pages: [makePage(0, 50), makePage(50, 50)],
      pageParams: [0, 50],
    };
    const filtered = filterInfiniteThreadsCache(
      data,
      (thread) => thread.thread_id !== "t-0",
    )!;
    expect(filtered.pages[0]?.threads).toHaveLength(49);
    expect(getInfiniteThreadsNextPageParam(filtered.pages[1]!)).toBe(100);
  });
});

describe("upsertThreadInInfiniteCache", () => {
  function seedClient(
    initial?: InfiniteData<InfiniteThreadsPage>,
  ): QueryClient {
    const client = new QueryClient();
    if (initial) {
      client.setQueryData([...INFINITE_THREADS_QUERY_KEY_PREFIX, {}], initial);
    }
    return client;
  }

  function readCache(
    client: QueryClient,
  ): InfiniteData<InfiniteThreadsPage> | undefined {
    return client.getQueryData([...INFINITE_THREADS_QUERY_KEY_PREFIX, {}]);
  }

  test("no-op when the infinite cache has not been initialised yet", () => {
    const client = seedClient();
    upsertThreadInInfiniteCache(client, makeThread("new"));
    expect(readCache(client)).toBeUndefined();
  });

  test("prepends a brand-new thread to the first page", () => {
    const client = seedClient({
      pages: [
        { threads: [makeThread("a"), makeThread("b")], nextOffset: null },
      ],
      pageParams: [0],
    });
    upsertThreadInInfiniteCache(client, makeThread("new"));
    const cache = readCache(client);
    expect(cache?.pages[0]?.threads.map((t) => t.thread_id)).toEqual([
      "new",
      "a",
      "b",
    ]);
  });

  test("merges into the existing entry instead of duplicating it", () => {
    const existing = makeThread("a", "Old title");
    const client = seedClient({
      pages: [{ threads: [existing, makeThread("b")], nextOffset: null }],
      pageParams: [0],
    });
    // Simulate an onCreated upsert that races with a thread already in cache:
    // the cache copy should win for title/metadata (it represents later state),
    // but no duplicate row should appear.
    upsertThreadInInfiniteCache(client, {
      ...makeThread("a", "New title"),
      status: "busy",
    });
    const cache = readCache(client);
    const ids = cache?.pages[0]?.threads.map((t) => t.thread_id);
    expect(ids).toEqual(["a", "b"]);
    expect(cache?.pages[0]?.threads[0]?.values.title).toBe("Old title");
  });
});
