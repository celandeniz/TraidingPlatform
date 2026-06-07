import type {
  OrdersResponse,
  PositionsResponse,
  ProfilesResponse,
  ScanResponse,
  SetupStatus,
  UniverseResponse,
} from "@/lib/types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") || "http://127.0.0.1:8765";

export function wsUrl(path = "/ws") {
  const url = new URL(path, API_BASE);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "content-type": "application/json",
      ...init?.headers,
    },
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export function getProfiles() {
  return api<ProfilesResponse>("/api/profiles");
}

export function activateProfile(name: string) {
  return api<ProfilesResponse & { ok: boolean }>("/api/profiles/activate", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export function getSetupStatus() {
  return api<SetupStatus>("/api/setup/status");
}

export function getPositions() {
  return api<PositionsResponse>("/api/positions");
}

export function getOrders() {
  return api<OrdersResponse>("/api/orders");
}

export function getUniverse(mode?: string) {
  const params = new URLSearchParams();
  if (mode) params.set("mode", mode);
  const suffix = params.toString() ? `?${params}` : "";
  return api<UniverseResponse>(`/api/universe${suffix}`);
}

export function getScan(mode: string, topN: number) {
  const params = new URLSearchParams({ mode, top_n: String(topN) });
  return api<ScanResponse>(`/api/scan?${params}`);
}
