import type { NextRequest } from "next/server";

function hasUnsafePathSegment(value: string) {
  return value
    .split(/[\\/]/)
    .some((segment) => segment === "." || segment === "..");
}

function encodePath(value: string) {
  return value.split("/").map(encodeURIComponent).join("/");
}

export async function GET(
  request: NextRequest,
  {
    params,
  }: {
    params: Promise<{
      thread_id: string;
      artifact_path?: string[] | undefined;
    }>;
  },
) {
  const threadId = (await params).thread_id;
  let artifactPath = (await params).artifact_path?.join("/") ?? "";
  if (
    !artifactPath.startsWith("mnt/") ||
    hasUnsafePathSegment(threadId) ||
    hasUnsafePathSegment(artifactPath)
  ) {
    return new Response("File not found", { status: 404 });
  }

  artifactPath = artifactPath.replace(/^mnt\//, "");
  const publicArtifactURL = new URL(
    `/demo/threads/${encodeURIComponent(threadId)}/${encodePath(artifactPath)}`,
    request.url,
  );
  const response = await fetch(publicArtifactURL);
  if (!response.ok) {
    return new Response("File not found", { status: 404 });
  }

  const headers = new Headers(response.headers);
  if (request.nextUrl.searchParams.get("download") === "true") {
    const filename = artifactPath.split("/").at(-1) ?? "artifact";
    headers.set("Content-Disposition", `attachment; filename="${filename}"`);
  }
  return new Response(response.body, {
    status: response.status,
    headers,
  });
}
