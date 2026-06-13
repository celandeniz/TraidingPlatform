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

export type TournamentGate = {
  passed: boolean;
  failures: string[];
};

export type TournamentReport = {
  name: string;
  kind: "trades" | "portfolio" | "pairs";
  metrics: {
    oos_sharpe?: number;
    per_trade_sharpe?: number;
    total_return_pct?: number;
    annual_return_pct?: number;
    max_drawdown_pct?: number;
    profit_factor?: number;
    n_trades?: number;
    n_rebalances?: number;
    significant?: boolean;
    [k: string]: unknown;
  };
  equity_curve: [string, number][];
  windows: { year?: number; return_pct?: number }[];
  gates: TournamentGate | null;
  error: string;
};

export type TournamentStatus = { running: boolean; progress: string; error: string };

export type TournamentLatest = {
  started_at: string;
  config_hash: string;
  reports: TournamentReport[];
  status?: TournamentStatus;
};

export type TournamentRuns = {
  runs: { file: string; started_at: string; n_strategies: number }[];
  status?: TournamentStatus;
};

export type PanelVote = {
  name: string;
  side: "long" | "short" | "pass";
  confidence: number;
  rationale: string;
};

export type PanelResult = {
  symbol: string;
  verdict: "long" | "short" | "pass";
  score: number;
  votes: PanelVote[];
  fundamentals_available: boolean;
  generated_at: string;
  cached: boolean;
};

export type VibeResearchResult = {
  ok: boolean;
  symbol: string;
  summary?: string;
  side?: "long" | "short" | "pass";
  confidence?: number;
  events?: number;
  detail?: string;
  source?: string;
};

export type SynthesisOutcome = {
  name: string;
  index: number;
  valid: boolean;
  reason?: string;
  metrics?: Record<string, number | string | boolean>;
  gates?: { passed?: boolean; failures?: string[] };
};

export type SynthesisResult = {
  ok: boolean;
  symbol: string;
  promoted?: string;
  n_candidates?: number;
  n_valid?: number;
  n_passing?: number;
  provider?: string;
  outcomes?: SynthesisOutcome[];
  detail?: string;
  source?: string;
};

export type GatewayReply = {
  ok: boolean;
  // success path carries intent/answer/data; the disabled path carries detail.
  intent?: string;
  answer?: string;
  data?: Record<string, unknown>;
  detail?: string;
  source?: "agent_gateway";
};
