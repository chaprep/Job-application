export class ApiError extends Error {
  constructor(
    message: string,
    public fields?: {
      can_override_links?: boolean;
      issues?: {
        field?: string;
        loc?: string[];
        message?: string;
        msg?: string;
      }[];
      findings?: { field: string; explanation: string }[];
    },
  ) {
    super(message);
  }
}

export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  let response: Response;
  try {
    response = await fetch(
      path.startsWith("/api/") || path === "/readiness"
        ? path
        : `/api/v1${path}`,
      { ...options, headers },
    );
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError")
      throw error;
    throw new ApiError(
      "Jab could not reach the local server. Check that it is running, then try again.",
    );
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(
      body?.error?.message ||
        `The request could not complete (${response.status}).`,
      body?.error?.fields,
    );
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}

export const post = <T>(path: string, body?: unknown, method = "POST") =>
  api<T>(path, {
    method,
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
export const pdfUrl = (id: number, download = false) =>
  `/api/v1/documents/${id}/pdf?download=${download}`;
export function safeUrl(value: string | null | undefined): string | undefined {
  if (!value) return;
  try {
    const url = new URL(value);
    if (["http:", "https:"].includes(url.protocol)) return url.href;
  } catch {
    /* Stored text may be an incomplete URL. */
  }
}
export const today = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
export const label = (value: string) =>
  ({
    needs_review: "Needs review",
    ready: "Ready",
    succeeded: "Complete",
    partial: "Needs attention",
    failed: "Needs attention",
    interrupted: "Interrupted",
    pending: "Pending",
    uploaded: "Uploaded",
    extracting: "Processing",
    queued: "Queued",
    running: "In progress",
    cover_letter: "Cover letter",
    resume: "Résumé",
  })[value] || value.replaceAll("_", " ").replace(/^./, (c) => c.toUpperCase());
export const dateLabel = (value?: string | null) =>
  value
    ? new Date(
        value.length === 10 ? `${value}T12:00:00` : value,
      ).toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
        year: "numeric",
      })
    : "Not recorded";
export const activeTask = (tasks?: { status: string }[]) =>
  tasks?.some((t) => ["queued", "running"].includes(t.status)) || false;
