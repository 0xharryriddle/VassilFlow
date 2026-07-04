export function vassilflowAliasFor(name: string): string | undefined {
  return undefined;
}

function legacyNamesForVassilflow(name: string): string[] {
  return [];
}

export function envValue(name: string): string | undefined {
  return process.env[name];
}
