import Constants from "expo-constants";
import { Platform } from "react-native";

export type SessionHeaders = {
  accessToken: string | null;
  sessionEmail: string | null;
  sessionRole: string | null;
};

function expoDevHost(): string | null {
  const hostUri =
    Constants.expoConfig?.hostUri ??
    (Constants as { manifest2?: { extra?: { expoClient?: { hostUri?: string } } } })
      .manifest2?.extra?.expoClient?.hostUri ??
    (Constants as { manifest?: { debuggerHost?: string } }).manifest?.debuggerHost ??
    null;
  if (!hostUri) return null;
  const host = String(hostUri).split(":")[0]?.trim();
  if (!host || host === "127.0.0.1" || host === "localhost") return null;
  return host;
}

function resolveApiBaseUrl(configured: string): string {
  try {
    const url = new URL(configured);
    const isLoopback = url.hostname === "127.0.0.1" || url.hostname === "localhost";
    // Web and loopback-friendly platforms can keep localhost.
    if (!isLoopback || Platform.OS === "web") {
      return configured.replace(/\/+$/, "");
    }
    // On a physical device / Expo Go, 127.0.0.1 is the phone — use the Metro host IP.
    const host = expoDevHost();
    if (host) {
      url.hostname = host;
      return url.toString().replace(/\/+$/, "");
    }
  } catch {
    // fall through
  }
  return configured.replace(/\/+$/, "");
}

function appExtra() {
  const extra = (Constants.expoConfig?.extra ?? {}) as Record<string, unknown>;
  return {
    apiBaseUrl: resolveApiBaseUrl(String(extra.apiBaseUrl ?? "http://127.0.0.1:8090")),
    authDisableSso: String(extra.authDisableSso ?? "true") === "true",
    cognitoIssuer: String(extra.cognitoIssuer ?? ""),
    cognitoClientId: String(extra.cognitoClientId ?? ""),
    cognitoScope: String(extra.cognitoScope ?? "relaydesk-api/access"),
  };
}

export const runtimeConfig = appExtra();

export function formatApiErrorDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object") {
          const record = item as Record<string, unknown>;
          return String(record.msg ?? JSON.stringify(item));
        }
        return String(item);
      })
      .join("; ");
  }
  if (detail && typeof detail === "object") {
    const record = detail as Record<string, unknown>;
    if (typeof record.message === "string") return record.message;
    if (typeof record.detail === "string") return record.detail;
    return JSON.stringify(record);
  }
  return "Request failed";
}

function buildUrl(path: string, query?: Record<string, string | number | undefined | null>) {
  const base = runtimeConfig.apiBaseUrl.replace(/\/+$/, "");
  const url = new URL(path.replace(/^\/+/, ""), `${base}/`);
  Object.entries(query ?? {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(key, String(value));
    }
  });
  return url.toString();
}

function buildHeaders(session: SessionHeaders, headers?: Record<string, string>) {
  const merged: Record<string, string> = { ...(headers ?? {}) };
  if (session.accessToken) {
    merged.Authorization = `Bearer ${session.accessToken}`;
  }
  if (session.sessionEmail) {
    merged["x-relaydesk-user-email"] = session.sessionEmail;
  }
  if (session.sessionRole) {
    merged["x-relaydesk-user-role"] = session.sessionRole;
  }
  return merged;
}

export async function apiRequest<T>(
  session: SessionHeaders,
  path: string,
  init?: RequestInit,
  query?: Record<string, string | number | undefined | null>,
): Promise<T> {
  const response = await fetch(buildUrl(path, query), {
    ...init,
    headers: buildHeaders(session, init?.headers as Record<string, string> | undefined),
  });

  if (!response.ok) {
    const text = await response.text();
    let detail: unknown = text;
    try {
      const json = JSON.parse(text) as { detail?: unknown };
      detail = json.detail ?? text;
    } catch {
      detail = text;
    }
    throw new Error(formatApiErrorDetail(detail));
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

export async function apiJson<T>(
  session: SessionHeaders,
  path: string,
  method: string,
  body?: unknown,
  query?: Record<string, string | number | undefined | null>,
): Promise<T> {
  return apiRequest<T>(
    session,
    path,
    {
      method,
      headers: { "content-type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    },
    query,
  );
}

export async function apiUpload<T>(
  session: SessionHeaders,
  path: string,
  file: { uri: string; name: string; mimeType?: string | null },
  query?: Record<string, string | number | undefined | null>,
): Promise<T> {
  const form = new FormData();
  form.append("file", {
    uri: file.uri,
    name: file.name,
    type: file.mimeType ?? "application/octet-stream",
  } as never);

  return apiRequest<T>(
    session,
    path,
    {
      method: "POST",
      body: form,
    },
    query,
  );
}
