export function vassilflowAliasFor(name: string): string | undefined {
  if (name.startsWith("DEER_FLOW_")) {
    return `VASSILFLOW_${name.slice("DEER_FLOW_".length)}`;
  }
  if (name.startsWith("DEERFLOW_")) {
    return `VASSILFLOW_${name.slice("DEERFLOW_".length)}`;
  }
  return undefined;
}

export function envValue(name: string): string | undefined {
  const alias = vassilflowAliasFor(name);
  return (alias ? process.env[alias] : undefined) ?? process.env[name];
}
