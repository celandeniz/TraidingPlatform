export type Runtime = {
  active_profile?: string | null;
  profile_mode?: string;
  profile_broker?: string;
  trading_mode?: string;
  live_trading_enabled?: boolean;
  paper_mode?: boolean;
  risk_enabled?: boolean;
};

export type ProfilesResponse = {
  profiles: Array<{
    name: string;
    description?: string;
    mode?: string;
    broker?: string;
    features?: Record<string, boolean>;
  }>;
  active?: string | null;
  active_features?: Record<string, boolean>;
  runtime?: Runtime;
};

export type SetupStatus = {
  optional_deps: Record<string, boolean>;
  api_keys_set: Record<string, boolean>;
  llm_providers_reachable: Record<string, boolean>;
};

export type Position = {
  symbol?: string;
  qty?: number;
  quantity?: number;
  avg_entry_price?: number;
  avg_price?: number;
  market_value?: number;
  last_price?: number;
  unrealized_pl?: number;
  unrealized_pnl?: number;
  side?: string;
  [key: string]: unknown;
};

export type PositionsResponse = {
  account: Record<string, unknown>;
  positions: Position[];
};

export type OrderRecord = {
  id: string;
  state?: string;
  message?: string;
  note?: string;
  request?: Record<string, unknown>;
  result?: Record<string, unknown> | null;
  history?: Array<Record<string, unknown>>;
};

export type OrdersResponse = {
  orders: OrderRecord[];
};

export type UniverseResponse = {
  mode?: string;
  source?: string;
  count?: number;
  symbols?: string[];
  [key: string]: unknown;
};

export type ScanCandidate = {
  symbol?: string;
  score?: number;
  side?: string;
  price?: number;
  close?: number;
  regime?: string;
  reason?: string;
  strategy?: string;
  [key: string]: unknown;
};

export type ScanResponse = {
  timeframe?: string;
  scanned?: number;
  skipped?: number;
  candidates: ScanCandidate[];
  note?: string;
};

export type WsEvent = {
  type?: string;
  symbol?: string;
  side?: string;
  strategy?: string;
  strength?: number;
  close?: number;
  qty?: number;
  status?: string;
  detail?: string;
  candidates?: ScanCandidate[];
  [key: string]: unknown;
};
