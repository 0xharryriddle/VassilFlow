export function vassilflowAliasFor(name: string): string | undefined {
  if (name.startsWith("DEER_FLOW_")) {
    return `VASSILFLOW_${name.slice("DEER_FLOW_".length)}`;
  }
  if (name.startsWith("DEERFLOW_")) {
    return `VASSILFLOW_${name.slice("DEERFLOW_".length)}`;
  }
  return undefined;
}

function legacyNamesForVassilflow(name: string): string[] {
  if (!name.startsWith("VASSILFLOW_")) {
    return [];
  }
  const suffix = name.slice("VASSILFLOW_".length);
  return [`DEER_FLOW_${suffix}`, `DEERFLOW_${suffix}`];
}

export function envValue(name: string): string | undefined {
  const alias = vassilflowAliasFor(name);
  if (alias) {
    return process.env[alias] ?? process.env[name];
  }

  for (const legacyName of legacyNamesForVassilflow(name)) {
    const value = process.env[legacyName];
    if (value !== undefined) {
      return process.env[name] ?? value;
    }
  }
  return process.env[name];
}
