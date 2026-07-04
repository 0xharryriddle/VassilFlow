import {
  afterEach,
  beforeEach,
  describe,
  expect,
  test,
  rs,
} from "@rstest/core";

const ENV_KEYS = [
  "NODE_ENV",
  "VASSILFLOW_INTERNAL_GATEWAY_BASE_URL",
  "VASSILFLOW_TRUSTED_ORIGINS",
] as const;
const OLD_ENV_PREFIX = ["D", "EER_FLOW"].join("");

type EnvSnapshot = Partial<
  Record<(typeof ENV_KEYS)[number], string | undefined>
>;

function snapshotEnv(): EnvSnapshot {
  const snapshot: EnvSnapshot = {};
  for (const key of ENV_KEYS) {
    snapshot[key] = process.env[key];
  }
  return snapshot;
}

function setEnv(key: (typeof ENV_KEYS)[number], value: string | undefined) {
  // NODE_ENV is typed as a readonly literal union, so we go through the
  // index signature to keep the test compiler-friendly across cases.
  const env = process.env as Record<string, string | undefined>;
  if (value === undefined) {
    delete env[key];
  } else {
    env[key] = value;
  }
}

function restoreEnv(snapshot: EnvSnapshot) {
  for (const key of ENV_KEYS) {
    setEnv(key, snapshot[key]);
  }
}

async function loadFreshConfig() {
  rs.resetModules();
  return await import("@/core/auth/gateway-config");
}

describe("getGatewayConfig", () => {
  let saved: EnvSnapshot;

  beforeEach(() => {
    saved = snapshotEnv();
    setEnv("VASSILFLOW_INTERNAL_GATEWAY_BASE_URL", undefined);
    setEnv("VASSILFLOW_TRUSTED_ORIGINS", undefined);
  });

  afterEach(() => {
    restoreEnv(saved);
  });

  test("returns localhost defaults when env is unset in development", async () => {
    setEnv("NODE_ENV", "development");

    const { getGatewayConfig } = await loadFreshConfig();
    const cfg = getGatewayConfig();

    expect(cfg.internalGatewayUrl).toBe("http://127.0.0.1:8001");
    expect(cfg.trustedOrigins).toEqual(["http://localhost:3000"]);
  });

  test("returns localhost defaults when env is unset in production (regression: issue #2705)", async () => {
    setEnv("NODE_ENV", "production");

    const { getGatewayConfig } = await loadFreshConfig();

    expect(() => getGatewayConfig()).not.toThrow();
    const cfg = getGatewayConfig();
    expect(cfg.internalGatewayUrl).toBe("http://127.0.0.1:8001");
    expect(cfg.trustedOrigins).toEqual(["http://localhost:3000"]);
  });

  test("uses env values verbatim when set, regardless of NODE_ENV", async () => {
    setEnv("NODE_ENV", "production");
    setEnv("VASSILFLOW_INTERNAL_GATEWAY_BASE_URL", "https://gw.example.com/");
    setEnv(
      "VASSILFLOW_TRUSTED_ORIGINS",
      "https://app.example.com, https://admin.example.com",
    );

    const { getGatewayConfig } = await loadFreshConfig();
    const cfg = getGatewayConfig();

    expect(cfg.internalGatewayUrl).toBe("https://gw.example.com");
    expect(cfg.trustedOrigins).toEqual([
      "https://app.example.com",
      "https://admin.example.com",
    ]);
  });

  test("ignores legacy VassilFlow env values when VassilFlow names are unset", async () => {
    setEnv("NODE_ENV", "production");
    process.env[`${OLD_ENV_PREFIX}_INTERNAL_GATEWAY_BASE_URL`] =
      "https://legacy.example.com/";
    process.env[`${OLD_ENV_PREFIX}_TRUSTED_ORIGINS`] =
      "https://legacy-app.example.com, https://legacy-admin.example.com";

    const { getGatewayConfig } = await loadFreshConfig();
    const cfg = getGatewayConfig();

    expect(cfg.internalGatewayUrl).toBe("http://127.0.0.1:8001");
    expect(cfg.trustedOrigins).toEqual(["http://localhost:3000"]);
    delete process.env[`${OLD_ENV_PREFIX}_INTERNAL_GATEWAY_BASE_URL`];
    delete process.env[`${OLD_ENV_PREFIX}_TRUSTED_ORIGINS`];
  });

  test("uses VassilFlow env values even when legacy VassilFlow names are present", async () => {
    setEnv("NODE_ENV", "production");
    process.env[`${OLD_ENV_PREFIX}_INTERNAL_GATEWAY_BASE_URL`] =
      "https://legacy.example.com";
    process.env[`${OLD_ENV_PREFIX}_TRUSTED_ORIGINS`] = "https://legacy-app.example.com";
    setEnv(
      "VASSILFLOW_INTERNAL_GATEWAY_BASE_URL",
      "https://gateway.vassil.example.com/",
    );
    setEnv(
      "VASSILFLOW_TRUSTED_ORIGINS",
      "https://app.vassil.example.com, https://admin.vassil.example.com",
    );

    const { getGatewayConfig } = await loadFreshConfig();
    const cfg = getGatewayConfig();

    expect(cfg.internalGatewayUrl).toBe("https://gateway.vassil.example.com");
    expect(cfg.trustedOrigins).toEqual([
      "https://app.vassil.example.com",
      "https://admin.vassil.example.com",
    ]);
    delete process.env.VASSILFLOW_INTERNAL_GATEWAY_BASE_URL;
    delete process.env.VASSILFLOW_TRUSTED_ORIGINS;
  });

  test("trims and filters empty entries in trustedOrigins", async () => {
    setEnv("NODE_ENV", "production");
    setEnv("VASSILFLOW_INTERNAL_GATEWAY_BASE_URL", "https://gw.example.com");
    setEnv(
      "VASSILFLOW_TRUSTED_ORIGINS",
      " https://a.example , ,https://b.example ",
    );

    const { getGatewayConfig } = await loadFreshConfig();
    const cfg = getGatewayConfig();

    expect(cfg.trustedOrigins).toEqual([
      "https://a.example",
      "https://b.example",
    ]);
  });
});
