import type {
  OrdersResponse,
  PanelResult,
  PositionsResponse,
  ProfilesResponse,
  ScanResponse,
  SetupStatus,
  TournamentLatest,
  TournamentRuns,
  GatewayReply,
  SynthesisResult,
  UniverseResponse,
  VibeResearchResult,
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

export function getTournamentLatest() {
  return api<TournamentLatest>("/api/tournament/latest");
}

export function getTournamentRuns() {
  return api<TournamentRuns>("/api/tournament/runs");
}

export function runTournament() {
  return api<{ ok: boolean; running: boolean }>("/api/tournament/run", {
    method: "POST",
  });
}

export function getPanel(symbol: string, refresh = false) {
  return api<PanelResult>(
    `/api/panel/${encodeURIComponent(symbol)}${refresh ? "?refresh=true" : ""}`,
  );
}

export function getVibeResearch(symbol: string) {
  return api<VibeResearchResult>(
    `/api/vibe/research/${encodeURIComponent(symbol)}`,
  );
}

export function runSynthesis(body: {
  text: string;
  symbol: string;
  timeframe?: string;
  n_candidates?: number;
  promote?: boolean;
}) {
  return api<SynthesisResult>("/api/synthesis", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function askGateway(message: string) {
  return api<GatewayReply>("/api/agent/gateway", {
    method: "POST",
    body: JSON.stringify({ message }),
  });
}
