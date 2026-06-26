import { envValue } from "../env-aliases";

import type { User } from "./types";

export const AUTH_DISABLED_USER: User = {
  id: "default",
  email: "default@test.local",
  system_role: "admin",
  needs_setup: false,
  oauth_provider: null,
};

const PRODUCTION_ENV_VALUES = new Set(["prod", "production"]);

function isExplicitProductionEnvironment() {
  return ["VASSILFLOW_ENV", "ENVIRONMENT"].some((name) =>
    PRODUCTION_ENV_VALUES.has((envValue(name) ?? "").trim().toLowerCase()),
  );
}

export function isAuthDisabledMode() {
  return (
    envValue("VASSILFLOW_AUTH_DISABLED") === "1" &&
    !isExplicitProductionEnvironment()
  );
}
