import {
  afterEach,
  beforeEach,
  describe,
  expect,
  test,
  rs,
} from "@rstest/core";

import {
  AGENT_CREATE_SAVE_HINT_KEY,
  DEFAULT_LOCAL_SETTINGS,
  LOCAL_SETTINGS_KEY,
  THREAD_MODEL_KEY_PREFIX,
  getLocalSettings,
  getThreadModelName,
  hasSeenAgentCreateSaveHint,
  markAgentCreateSaveHintSeen,
  saveLocalSettings,
  saveThreadModelName,
} from "@/core/settings/local";

test("defaults token usage to header total plus per-turn breakdown", () => {
  expect(DEFAULT_LOCAL_SETTINGS.tokenUsage).toEqual({
    headerTotal: true,
    inlineMode: "per_turn",
  });
});

function makeLocalStorage() {
  const values = new Map<string, string>();
  return {
    getItem: rs.fn((key: string) => values.get(key) ?? null),
    setItem: rs.fn((key: string, value: string) => {
      values.set(key, value);
    }),
    removeItem: rs.fn((key: string) => {
      values.delete(key);
    }),
    clear: rs.fn(() => {
      values.clear();
    }),
  } as unknown as Storage;
}

describe("VassilFlow localStorage keys", () => {
  beforeEach(() => {
    rs.stubGlobal("window", {});
    rs.stubGlobal("localStorage", makeLocalStorage());
  });

  afterEach(() => {
    rs.unstubAllGlobals();
  });

  test("uses VassilFlow keys as the primary storage namespace", () => {
    expect(LOCAL_SETTINGS_KEY).toBe("vassilflow.local-settings");
    expect(THREAD_MODEL_KEY_PREFIX).toBe("vassilflow.thread-model.");
    expect(AGENT_CREATE_SAVE_HINT_KEY).toBe(
      "vassilflow.agent-create.save-hint-seen",
    );
  });

  test("ignores legacy local settings namespace", () => {
    localStorage.setItem("deerflow.local-settings", JSON.stringify({ context: { mode: "ultra" } }));

    expect(getLocalSettings()).toEqual(DEFAULT_LOCAL_SETTINGS);
    expect(localStorage.getItem(LOCAL_SETTINGS_KEY)).toBeNull();
  });

  test("loads current local settings", () => {
    localStorage.setItem("deerflow.local-settings", JSON.stringify({ context: { mode: "ultra" } }));
    localStorage.setItem(
      LOCAL_SETTINGS_KEY,
      JSON.stringify({ context: { mode: "flash" } }),
    );

    expect(getLocalSettings().context.mode).toBe("flash");
  });

  test("saves local settings to the VassilFlow key", () => {
    localStorage.setItem("deerflow.local-settings", JSON.stringify({ context: { mode: "ultra" } }));
    saveLocalSettings({
      ...DEFAULT_LOCAL_SETTINGS,
      context: {
        ...DEFAULT_LOCAL_SETTINGS.context,
        mode: "pro",
      },
    });

    expect(localStorage.getItem("deerflow.local-settings")).not.toBeNull();
    expect(localStorage.getItem(LOCAL_SETTINGS_KEY)).toContain('"mode":"pro"');
  });

  test("ignores legacy thread model overrides", () => {
    localStorage.setItem("deerflow.thread-model.thread-1", "model-a");

    expect(getThreadModelName("thread-1")).toBeUndefined();
    expect(localStorage.getItem(`${THREAD_MODEL_KEY_PREFIX}thread-1`)).toBeNull();
  });

  test("saves thread model overrides to the VassilFlow prefix", () => {
    localStorage.setItem("deerflow.thread-model.thread-1", "model-a");

    saveThreadModelName("thread-1", "model-b");

    expect(localStorage.getItem("deerflow.thread-model.thread-1")).toBe("model-a");
    expect(localStorage.getItem(`${THREAD_MODEL_KEY_PREFIX}thread-1`)).toBe(
      "model-b",
    );
  });

  test("ignores the legacy agent-create save hint flag", () => {
    localStorage.setItem("deerflow.agent-create.save-hint-seen", "1");

    expect(hasSeenAgentCreateSaveHint()).toBe(false);
    expect(localStorage.getItem(AGENT_CREATE_SAVE_HINT_KEY)).toBeNull();
  });

  test("marks the agent-create save hint with the VassilFlow key", () => {
    localStorage.setItem("deerflow.agent-create.save-hint-seen", "1");

    markAgentCreateSaveHintSeen();

    expect(localStorage.getItem(AGENT_CREATE_SAVE_HINT_KEY)).toBe("1");
    expect(localStorage.getItem("deerflow.agent-create.save-hint-seen")).toBe("1");
  });
});
