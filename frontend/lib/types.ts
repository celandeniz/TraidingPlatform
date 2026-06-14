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

export type BacktestResult = {
  ok: boolean;
  detail?: string;
  scenario?: string;
  symbol?: string;
  n_trades?: number;
  win_rate?: number;
  total_return_pct?: number;
  profit_factor?: number;
  max_drawdown_pct?: number;
  sharpe?: number;
  buy_hold_pct?: number;
  excess_vs_buy_hold?: number;
  exposure_pct?: number;
  significant?: boolean;
  significance_label?: string;
  p_value?: number;
  available_strategies?: string[];
  timeframes?: string[];
  ai?: { verdict?: string; caveats?: string[]; available?: boolean };
};

export type WalkForwardFold = {
  fold: number;
  chosen: string;
  is_return_pct: number;
  oos_return_pct: number;
  oos_buy_hold_pct: number;
  oos_excess_pct: number;
  oos_trades: number;
  oos_start: string;
  oos_end: string;
};

export type WalkForwardResult = {
  ok: boolean;
  detail?: string;
  symbol?: string;
  timeframe?: string;
  regime_filtered?: boolean;
  n_folds?: number;
  avg_is_return?: number;
  avg_oos_return?: number;
  avg_oos_excess?: number;
  degradation_pct?: number;
  oos_positive_folds?: number;
  oos_beat_bh_folds?: number;
  verdict?: string;
  folds?: WalkForwardFold[];
};

export type ScenarioRow = {
  scenario: string;
  n_trades: number;
  win_rate: number;
  total_return_pct: number;
  profit_factor: number;
  max_drawdown_pct: number;
  sharpe: number;
  buy_hold_pct: number;
  excess_vs_buy_hold: number;
};

export type ScenariosResult = { ok: boolean; detail?: string; count?: number; rows: ScenarioRow[] };

export type SelectVerdict = {
  symbol: string;
  tradable: boolean;
  avg_oos_return: number;
  oos_beat_bh_folds: number;
  n_folds: number;
  reason: string;
};

export type SelectResult = {
  ok: boolean;
  detail?: string;
  tradable?: string[];
  excluded?: string[];
  all_avg_oos?: number;
  tradable_avg_oos?: number;
  verdicts?: SelectVerdict[];
};

export type EquityPoint = { time?: string; equity?: number; [k: string]: unknown };
export type EquityCurveResult = { available: boolean; detail?: string; points: EquityPoint[] };

export type GreeksResult = {
  ok: boolean;
  detail?: string;
  [k: string]: unknown; // price, delta, gamma, theta, vega, rho, source (from gs_analytics.as_dict)
};
