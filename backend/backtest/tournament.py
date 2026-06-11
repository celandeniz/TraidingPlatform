"""Strategy tournament — run every candidate, gate hard, rank honestly.

Gates (spec): max drawdown <= 20%, profit factor >= 1.3, >= 100 trades
(portfolio strategies: >= 24 rebalances), statistical significance. Gate-failers
stay on the leaderboard with the failed gate named — no survivorship hiding.
Ranking: passers by out-of-sample Sharpe, descending; then failers; errors last.

`runners` maps name -> callable(config) -> StrategyReport. The default runners
wire real data (DailyBarCache, EarningsCalendar, 1m provider history); tests
inject fakes. Every runner is exception-isolated: a crash becomes an error row,
never a dead tournament (spec: Error Handling).

New strategies ship with fixed default parameters (no in-sample parameter
search), so the whole backtest period is out-of-sample by construction; per-year
breakdowns are reported for stability. Parameter search, when added, must go
through walkforward.py's IS/OOS split.

Results persist as JSON under backend/store/tournament/.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional

DEFAULT_STORE = Path(__file__).resolve().parent.parent / "store" / "tournament"

GATES = {
    "max_drawdown_pct": 20.0,
    "profit_factor": 1.3,
    "min_trades": 100,
    "min_rebalances": 24,
}


@dataclass
class GateResult:
    passed: bool = True
    failures: list = field(default_factory=list)


@dataclass
class StrategyReport:
    name: str
    kind: str = "trades"             # "trades" | "portfolio" | "pairs"
    metrics: dict = field(default_factory=dict)
    equity_curve: list = field(default_factory=list)
    windows: list = field(default_factory=list)   # per-year / per-fold detail
    gates: Optional[dict] = None
    error: str = ""


@dataclass
class TournamentRun:
    started_at: str = ""
    config_hash: str = ""
    reports: list = field(default_factory=list)
    ranked: list = field(default_factory=list)


def apply_gates(report: StrategyReport) -> GateResult:
    if report.error:
        return GateResult(passed=False, failures=[f"error: {report.error}"])
    m = report.metrics
    out = GateResult()
    if m.get("max_drawdown_pct", 1e9) > GATES["max_drawdown_pct"]:
        out.failures.append(
            f"max drawdown {m.get('max_drawdown_pct'):.1f}% > {GATES['max_drawdown_pct']}%")
    if m.get("profit_factor", 0.0) < GATES["profit_factor"]:
        out.failures.append(
            f"profit factor {m.get('profit_factor'):.2f} < {GATES['profit_factor']}")
    if report.kind == "portfolio":
        if m.get("n_rebalances", 0) < GATES["min_rebalances"]:
            out.failures.append(
                f"rebalances {m.get('n_rebalances', 0)} < {GATES['min_rebalances']}")
    else:
        if m.get("n_trades", 0) < GATES["min_trades"]:
            out.failures.append(
                f"trades {m.get('n_trades', 0)} < {GATES['min_trades']}")
    if not m.get("significant", False):
        out.failures.append("returns not statistically significant")
    out.passed = not out.failures
    return out


def rank_reports(reports: list) -> list:
    for r in reports:
        r.gates = asdict(apply_gates(r))
    passers = [r for r in reports if r.gates["passed"]]
    failers = [r for r in reports if not r.gates["passed"] and not r.error]
    errors = [r for r in reports if r.error]
    def key(r):
        return r.metrics.get("oos_sharpe", -1e9)
    return sorted(passers, key=key, reverse=True) + \
        sorted(failers, key=key, reverse=True) + errors


def run_tournament(config: dict, *, runners: Optional[dict] = None,
                   progress: Optional[Callable[[str, int, int], None]] = None) -> TournamentRun:
    runners = runners if runners is not None else default_runners(config)
    reports: list[StrategyReport] = []
    total = len(runners)
    for i, (name, fn) in enumerate(runners.items(), 1):
        if progress:
            progress(name, i, total)
        try:
            reports.append(fn(config))
        except Exception as exc:     # noqa: BLE001 — spec: never kill the run
            reports.append(StrategyReport(name=name, error=str(exc)))
    run = TournamentRun(
        started_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        config_hash=hashlib.sha256(
            json.dumps(config, sort_keys=True, default=str).encode()).hexdigest()[:12],
        reports=reports,
    )
    run.ranked = rank_reports(reports)
    return run


# ---------------------------------------------------------------- persistence

def save_run(run: TournamentRun, *, store_dir: Path | str = DEFAULT_STORE) -> Path:
    store = Path(store_dir)
    store.mkdir(parents=True, exist_ok=True)
    payload = {
        "started_at": run.started_at, "config_hash": run.config_hash,
        "reports": [asdict(r) for r in run.ranked],
    }
    name = f"run_{run.started_at.replace(':', '').replace('-', '')}.json"
    path = store / name
    path.write_text(json.dumps(payload, indent=1, default=str))
    return path


def list_runs(*, store_dir: Path | str = DEFAULT_STORE) -> list[dict]:
    store = Path(store_dir)
    if not store.exists():
        return []
    out = []
    for p in sorted(store.glob("run_*.json"), reverse=True):
        data = json.loads(p.read_text())
        out.append({"file": p.name, "started_at": data.get("started_at"),
                    "n_strategies": len(data.get("reports", []))})
    return out


def load_latest(*, store_dir: Path | str = DEFAULT_STORE) -> Optional[dict]:
    store = Path(store_dir)
    files = sorted(store.glob("run_*.json"), reverse=True) if store.exists() else []
    return json.loads(files[0].read_text()) if files else None


# ------------------------------------------------------------ default runners

def _trade_metrics(trades_pct: list, equity_curve: list) -> dict:
    """Shared metric block from per-trade % returns (engine-style strategies)."""
    from .stats import significance

    if not trades_pct:
        return {"oos_sharpe": 0.0, "n_trades": 0, "profit_factor": 0.0,
                "max_drawdown_pct": 0.0, "total_return_pct": 0.0,
                "significant": False}
    wins = sum(r for r in trades_pct if r > 0)
    losses = -sum(r for r in trades_pct if r < 0)
    pf = wins / losses if losses > 0 else 999.0
    mean = sum(trades_pct) / len(trades_pct)
    var = sum((r - mean) ** 2 for r in trades_pct) / len(trades_pct)
    sharpe = mean / (var ** 0.5) if var > 0 else 0.0
    curve = list(equity_curve)
    if not curve:
        eq = 1.0
        for r in trades_pct:
            eq *= (1 + r / 100.0)
            curve.append(eq)
    peak, max_dd = 1.0, 0.0
    for e in curve:
        peak = max(peak, e)
        max_dd = max(max_dd, (peak - e) / peak)
    sg = significance(trades_pct)
    return {"oos_sharpe": round(sharpe, 3), "n_trades": len(trades_pct),
            "profit_factor": round(min(pf, 999.0), 3),
            "max_drawdown_pct": round(max_dd * 100.0, 3),
            "total_return_pct": round((curve[-1] - 1.0) * 100.0, 3) if curve else 0.0,
            "significant": bool(sg.significant), "p_value": sg.p_value}


def _pf_from_daily(daily: list) -> float:
    wins = sum(r for r in daily if r > 0)
    losses = -sum(r for r in daily if r < 0)
    return round(wins / losses, 3) if losses > 0 else 999.0


def default_runners(config: dict) -> dict:
    """Wire real data sources. Heavy imports stay inside so tests never pay them."""
    from backend.data.daily_cache import DailyBarCache
    from backend.data.earnings import EarningsCalendar, EarningsUnavailable
    from backend.universe import load_universe

    tcfg = config.get("tournament", {})
    store = Path(__file__).resolve().parent.parent / "store"
    cache = DailyBarCache(store / "daily_cache")
    universe = sorted(load_universe(config))          # sorted: deterministic ties
    daily_symbols = sorted(tcfg.get("daily_symbols") or universe)
    intraday_symbols = sorted(tcfg.get("intraday_symbols") or universe[:20])
    lookback_1m = int(tcfg.get("intraday_lookback_bars", 30 * 390))
    cost_bps = float(tcfg.get("cost_bps", 5.0))

    def _provider():
        # Mirror the codebase's equity DataProvider construction from brokers.py /
        # runner.py: AlpacaProvider(key, secret, feed=feed) via build_data_provider.
        from backend.brokers import build_data_provider
        from backend.settings import get_settings, get_config as _get_cfg
        settings = get_settings()
        cfg = _get_cfg()
        return build_data_provider("equity", settings, cfg)

    def _daily_frames(symbols, extra=()):
        rep = cache.ensure(sorted(dict.fromkeys([*symbols, *extra])), min_years=3)
        return {s: cache.get(s) for s in rep.included}, rep

    def run_intraday(name, generate, params):
        def runner(cfg):
            provider = _provider()
            from .engine import CostModel, ExitParams, run_backtest
            all_trades = []
            n_sym = 0
            for sym in intraday_symbols:
                df = provider.get_recent_bars(sym, "1m", lookback_1m)
                if df is None or len(df) < 500:
                    continue
                n_sym += 1
                res = run_backtest(
                    df, lambda w: generate(w, **params),
                    exits=ExitParams(take_profit_pct=2.0, stop_loss_pct=1.0,
                                     allow_short=True),
                    costs=CostModel(1.0, 2.0), warmup=60, scenario=f"{name}:{sym}")
                all_trades.extend(t.ret_pct for t in res.trades)
            rep = StrategyReport(name=name, kind="trades",
                                 metrics=_trade_metrics(all_trades, []))
            rep.metrics["symbols_tested"] = n_sym
            return rep
        return runner

    def run_portfolio(name, strategy_cls, symbols=None):
        def runner(cfg):
            syms = symbols if symbols is not None else daily_symbols
            frames, rep = _daily_frames(syms, extra=["SPY"])
            from .portfolio_engine import run_portfolio_backtest
            res = run_portfolio_backtest(frames, strategy_cls(), cost_bps=cost_bps,
                                         config=cfg)
            if res.error:
                return StrategyReport(name=name, kind="portfolio", error=res.error)
            from .stats import significance
            sg = significance([r * 100.0 for r in res.daily_returns if r != 0.0])
            return StrategyReport(
                name=name, kind="portfolio",
                metrics={"oos_sharpe": res.sharpe,
                         "max_drawdown_pct": res.max_drawdown_pct,
                         "profit_factor": _pf_from_daily(res.daily_returns),
                         "n_rebalances": res.n_rebalances,
                         "total_return_pct": res.total_return_pct,
                         "annual_return_pct": res.annual_return_pct,
                         "significant": bool(sg.significant),
                         "excluded_symbols": rep.excluded},
                equity_curve=res.equity_curve[::5],     # downsample for JSON
                windows=[{"year": y, "return_pct": r} for y, r in res.yearly.items()],
            )
        return runner

    def run_earnings(cfg):
        from .engine import CostModel, ExitParams, run_backtest
        from backend.strategy.earnings_drift import generate as gen
        cal = EarningsCalendar(store / "earnings_cache")
        params = cfg.get("earnings_drift", {})
        frames, rep = _daily_frames(daily_symbols)
        all_trades = []
        unavailable = 0
        for sym, df in frames.items():
            try:
                dates = cal.get_dates(sym)
            except EarningsUnavailable:
                unavailable += 1
                continue
            res = run_backtest(
                df, lambda w, _d=dates: gen(w, earnings_dates=_d,
                                  gap_min_pct=params.get("gap_min_pct", 5.0),
                                  vol_mult=params.get("vol_mult", 1.5),
                                  hold_days=params.get("hold_days", 20),
                                  stop_pct=params.get("stop_pct", 10.0)),
                exits=ExitParams(take_profit_pct=1000.0, stop_loss_pct=10.0,
                                 allow_short=False),
                costs=CostModel(1.0, 2.0), warmup=25, scenario=f"pead:{sym}")
            all_trades.extend(t.ret_pct for t in res.trades)
        if frames and unavailable == len(frames):
            return StrategyReport(name="earnings_drift", kind="trades",
                                  error="earnings data unavailable")
        r = StrategyReport(name="earnings_drift", kind="trades",
                           metrics=_trade_metrics(all_trades, []))
        r.metrics["earnings_unavailable_symbols"] = unavailable
        r.metrics["excluded_symbols"] = rep.excluded
        return r

    def run_pairs(cfg):
        from backend.strategy.pairs_statarb import run_pairs_strategy
        p = cfg.get("pairs_statarb", {})
        frames, rep = _daily_frames(daily_symbols)
        kw = {k: v for k, v in p.items()
              if k in ("train_frac", "corr_min", "pval_max", "top_n", "z_entry",
                       "z_exit", "z_stop", "max_days", "hedge_window",
                       "cost_bps", "max_tests")}
        res = run_pairs_strategy(frames, **kw)
        if res["error"]:
            return StrategyReport(name="pairs_statarb", kind="pairs", error=res["error"])
        r = StrategyReport(name="pairs_statarb", kind="pairs",
                           metrics=_trade_metrics([t["ret_pct"] for t in res["trades"]], []))
        r.metrics["pairs"] = res["pairs"]
        r.metrics["excluded_symbols"] = rep.excluded
        return r

    from backend.strategy.gap_go import generate as gap_gen
    from backend.strategy.orb_breakout import generate as orb_gen
    from backend.strategy.sector_rotation import SectorRotationStrategy, SECTOR_ETFS
    from backend.strategy.xs_momentum import XsMomentumStrategy

    orb_p = dict(config.get("orb_breakout", {}))
    gap_p = dict(config.get("gap_go", {}))
    return {
        "orb_breakout": run_intraday("orb_breakout", orb_gen, orb_p),
        "gap_go": run_intraday("gap_go", gap_gen, gap_p),
        "xs_momentum": run_portfolio("xs_momentum", XsMomentumStrategy),
        # sector_rotation fetches only the 11 SPDR ETFs + SPY, not the full universe
        "sector_rotation": run_portfolio("sector_rotation", SectorRotationStrategy,
                                         symbols=SECTOR_ETFS),
        "earnings_drift": run_earnings,
        "pairs_statarb": run_pairs,
    }
