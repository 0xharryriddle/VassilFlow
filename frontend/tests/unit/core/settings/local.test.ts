import {
  afterEach,
  beforeEach,
  describe,
  expect,
  test,
  rs,
} from "@rstest/core";

import {
  DEFAULT_LOCAL_SETTINGS,
  LEGACY_LOCAL_SETTINGS_KEY,
  LEGACY_THREAD_MODEL_KEY_PREFIX,
  LOCAL_SETTINGS_KEY,
  THREAD_MODEL_KEY_PREFIX,
  getLocalSettings,
  getThreadModelName,
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
  });

  test("loads legacy local settings once and migrates them to the VassilFlow key", () => {
    localStorage.setItem(
      LEGACY_LOCAL_SETTINGS_KEY,
      JSON.stringify({ context: { mode: "ultra" } }),
    );

    expect(getLocalSettings().context.mode).toBe("ultra");
    expect(localStorage.getItem(LOCAL_SETTINGS_KEY)).toBe(
      JSON.stringify({ context: { mode: "ultra" } }),
    );
  });

  test("prefers current local settings over stale legacy settings", () => {
    localStorage.setItem(
      LEGACY_LOCAL_SETTINGS_KEY,
      JSON.stringify({ context: { mode: "ultra" } }),
    );
    localStorage.setItem(
      LOCAL_SETTINGS_KEY,
      JSON.stringify({ context: { mode: "flash" } }),
    );

    expect(getLocalSettings().context.mode).toBe("flash");
  });

  test("saves local settings to the VassilFlow key and removes stale legacy state", () => {
    localStorage.setItem(
      LEGACY_LOCAL_SETTINGS_KEY,
      JSON.stringify({ context: { mode: "ultra" } }),
    );
    saveLocalSettings({
      ...DEFAULT_LOCAL_SETTINGS,
      context: {
        ...DEFAULT_LOCAL_SETTINGS.context,
        mode: "pro",
      },
    });

    expect(localStorage.getItem(LEGACY_LOCAL_SETTINGS_KEY)).toBeNull();
    expect(localStorage.getItem(LOCAL_SETTINGS_KEY)).toContain('"mode":"pro"');
  });

  test("loads legacy thread model overrides and migrates them to the VassilFlow prefix", () => {
    localStorage.setItem(
      `${LEGACY_THREAD_MODEL_KEY_PREFIX}thread-1`,
      "model-a",
    );

    expect(getThreadModelName("thread-1")).toBe("model-a");
    expect(localStorage.getItem(`${THREAD_MODEL_KEY_PREFIX}thread-1`)).toBe(
      "model-a",
    );
  });

  test("saves thread model overrides to the VassilFlow prefix and removes legacy state", () => {
    localStorage.setItem(
      `${LEGACY_THREAD_MODEL_KEY_PREFIX}thread-1`,
      "model-a",
    );

    saveThreadModelName("thread-1", "model-b");

    expect(
      localStorage.getItem(`${LEGACY_THREAD_MODEL_KEY_PREFIX}thread-1`),
    ).toBeNull();
    expect(localStorage.getItem(`${THREAD_MODEL_KEY_PREFIX}thread-1`)).toBe(
      "model-b",
    );
  });
});
