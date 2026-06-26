import { afterEach, describe, expect, rs, test } from "@rstest/core";

async function loadThreadChatModule() {
  rs.resetModules();
  rs.doMock("next/navigation", () => ({
    useParams: () => ({ thread_id: "thread-1" }),
    usePathname: () => "/workspace/chats/thread-1",
    useSearchParams: () => new URLSearchParams(),
  }));

  return await import("@/components/workspace/chats/use-thread-chat");
}

afterEach(() => {
  rs.doUnmock("next/navigation");
  rs.unstubAllGlobals();
  rs.resetModules();
});

describe("thread chat reset events", () => {
  test("uses the VassilFlow event namespace with a legacy alias", async () => {
    const { LEGACY_THREAD_CHAT_RESET_EVENT, THREAD_CHAT_RESET_EVENT } =
      await loadThreadChatModule();

    expect(THREAD_CHAT_RESET_EVENT).toBe("vassilflow:thread-chat-reset");
    expect(LEGACY_THREAD_CHAT_RESET_EVENT).toBe("deer-flow:thread-chat-reset");
  });

  test("dispatches the VassilFlow reset event", async () => {
    const dispatchEvent = rs.fn();
    rs.stubGlobal("window", { dispatchEvent });
    rs.stubGlobal(
      "CustomEvent",
      class MockCustomEvent<T> {
        detail?: T;
        type: string;

        constructor(type: string, init?: CustomEventInit<T>) {
          this.type = type;
          this.detail = init?.detail;
        }
      },
    );

    const { THREAD_CHAT_RESET_EVENT, resetThreadChatAfterDelete } =
      await loadThreadChatModule();
    const detail = {
      deletedThreadId: "thread-1",
      nextPath: "/workspace/chats/new",
    };

    resetThreadChatAfterDelete(detail);

    expect(dispatchEvent).toHaveBeenCalledTimes(1);
    const event = dispatchEvent.mock.calls[0]?.[0] as CustomEvent<
      typeof detail
    >;
    expect(event.type).toBe(THREAD_CHAT_RESET_EVENT);
    expect(event.detail).toBe(detail);
  });
});
