import type { PageMapItem } from "nextra";

function externalPageNames(items: PageMapItem[]): Set<string> {
  const names = new Set<string>();
  for (const item of items) {
    if (!("data" in item)) continue;
    for (const [name, metadata] of Object.entries(item.data)) {
      if (
        metadata &&
        typeof metadata === "object" &&
        "type" in metadata &&
        metadata.type === "page"
      ) {
        names.add(name);
      }
    }
  }
  return names;
}

function docsRoute(base: string, route: string): string {
  if (route.startsWith(base)) return route;

  const localeBase = base.endsWith("/docs")
    ? base.slice(0, -"/docs".length)
    : "";
  let contentRoute = route;
  if (localeBase && contentRoute === localeBase) {
    contentRoute = "/";
  } else if (localeBase && contentRoute.startsWith(`${localeBase}/`)) {
    contentRoute = contentRoute.slice(localeBase.length);
  }
  if (contentRoute === "/") return base;
  return `${base}${contentRoute.startsWith("/") ? contentRoute : `/${contentRoute}`}`;
}

function rewritePageMap(
  base: string,
  items: PageMapItem[],
  excludedRoots: Set<string>,
  depth: number,
): PageMapItem[] {
  const rewritten: PageMapItem[] = [];
  for (const item of items) {
    if ("data" in item) {
      if (depth !== 0) {
        rewritten.push({ ...item });
        continue;
      }
      rewritten.push({
        ...item,
        data: Object.fromEntries(
          Object.entries(item.data).filter(
            ([name]) => !excludedRoots.has(name),
          ),
        ),
      });
      continue;
    }

    if (depth === 0 && excludedRoots.has(item.name)) continue;

    const next = { ...item, route: docsRoute(base, item.route) };
    if ("children" in next) {
      next.children = rewritePageMap(
        base,
        next.children,
        excludedRoots,
        depth + 1,
      );
    }
    rewritten.push(next);
  }
  return rewritten;
}

export function buildDocsPageMap(
  base: string,
  items: PageMapItem[],
): PageMapItem[] {
  return rewritePageMap(base, items, externalPageNames(items), 0);
}
