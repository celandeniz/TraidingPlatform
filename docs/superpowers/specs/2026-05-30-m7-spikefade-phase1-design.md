# M7 Spike-Fade — Phase 1 Design (Data + Signal Skeleton)

**Date:** 2026-05-30
**Status:** Approved for implementation planning
**Scope:** Phase 1 only (of the 5-phase M7 Spike-Fade build spec). Subsequent phases
(decision/options layer, paper execution, dashboard, live trading, catalyst research)
are out of scope here and will each get their own spec → plan → build cycle.

---

## 1. Goal & context

Build the data + signal skeleton for the M7 Spike-Fade system: stream live 1-minute
bars for the 7 Magnificent-7 symbols from Alpaca, compute indicators, generate
spike-fade buy/sell signals, classify the trend regime, and log every signal to both
the terminal and a persistent JSONL tape.

**This phase does NOT place, trigger, or simulate any trades.** No decision layer, no
options, no execution. Its value is a tested signal engine and an accumulating signal
tape that lets us evaluate signal quality before any capital is risked.

**Overall project goal (context):** path to auto-trading. We build paper-first with
clean adapter boundaries so the execution layer slots in later (Phase 3+) without
rewrites. Phase 1 establishes the `DataProvider` seam that makes that possible.

**Build approach:** live-WS-first (user choice). Get real signals printing against the
live Alpaca websocket soonest. Signal math is still written as pure, unit-testable
functions (costs nothing, helps later).

**Definition of Done:** with Alpaca paper keys in `.env`, running the runner during the
US session streams the 7 M7 symbols, prints live signal lines to the terminal, and
appends each signal event to `logs/tape_YYYY-MM-DD.jsonl`. Unit tests pass.

---

## 2. Universe

AAPL, MSFT, GOOGL, AMZN, NVDA, META, TSLA — fixed 7-symbol M7 universe, defined in
`config.yaml`. (Per-symbol volatility tiering from the main spec §3 is NOT used in
Phase 1; it only matters once the decision layer exists.)

---

## 3. Architecture & module layout

```
m7-spikefade/
├── backend/
│   ├── config.yaml          # universe, thresholds, regime params, feed
│   ├── settings.py          # reads .env (pydantic-settings): Alpaca keys, feed
│   ├── data/
│   │   ├── base.py          # DataProvider Protocol
│   │   └── alpaca_provider.py  # live WS 1-min bars + REST warmup
│   ├── strategy/
│   │   ├── indicators.py    # rsi, zscore, ema, vwap  (pure)
│   │   ├── spike_fade.py    # generate(df) -> SignalResult  (pure)
│   │   └── regime.py        # detect(df) -> "up"|"down"|"range"  (pure)
│   ├── store/
│   │   └── tape.py          # append signal events to logs/tape_YYYY-MM-DD.jsonl
│   ├── runner.py            # async: WS → on bar-close → signal → terminal + tape
│   └── tests/               # unit tests for indicators, spike_fade, regime
├── logs/                    # JSONL tapes (gitignored)
├── .env.example
├── requirements.txt
└── README.md
```

This is the Phase-1 subset of the main spec's §7.1 file tree. The `DataProvider` seam
(§7.2 of the main spec) is preserved so the Phase 3 execution adapter slots in cleanly.

### 3.1 Data flow

```
Alpaca WS (1-min bars, 7 symbols)
    → runner: maintain rolling per-symbol bar window (warmed via REST at startup)
    → on each CLOSED bar:
        → indicators (rsi, zscore, ema, vwap)
        → spike_fade.generate(df)  -> {buy, sell, z, rsi}
        → regime.detect(df)        -> "up"|"down"|"range"
        → emit signal line to terminal
        → append signal event to logs/tape_YYYY-MM-DD.jsonl
```

---

## 4. Signal logic (pure functions)

Per symbol, on a rolling 1-minute bar window:

```
ret = close.pct_change()
z   = (ret - rolling_mean(ret, Zw)) / rolling_std(ret, Zw)     # Zw = 20
rsi = RSI(close, 14)

buy_sig  = (rolling_min(z,  K) < -Z_ENTRY)      # sudden drop in last K bars
           AND (rolling_min(rsi, K) < RSI_OS)   # oversold
           AND (close > close.shift(1))         # reversal started

sell_sig = (rolling_max(z,  K) >  Z_ENTRY)
           AND (rolling_max(rsi, K) > RSI_OB)
           AND (close < close.shift(1))
```

**Defaults (from `config.yaml`):** `Zw=20, K=3, Z_ENTRY=2.0, RSI_OS=30, RSI_OB=70`.

**Function contracts:**
- `indicators`: `rsi(close, n)`, `zscore(series, w)`, `ema(close, n)`, `vwap(df)` — pure,
  return pandas Series.
- `spike_fade.generate(df) -> {"buy": bool, "sell": bool, "z": float, "rsi": float}`
  (evaluated for the last/closed bar).
- `regime.detect(df) -> "up" | "down" | "range"` — based on `EMA(50)` slope vs a
  configurable threshold: `abs(EMA50_slope) < threshold → "range"`, else sign of slope.

In Phase 1 the regime is **logged alongside** each signal. No signal suppression by
regime yet — that is the decision layer's job in Phase 2.

---

## 5. Data layer

- **`DataProvider` Protocol** (`data/base.py`): `stream_bars(symbols, handler)` and
  `get_recent_bars(symbol, timeframe, lookback) -> pd.DataFrame`.
- **`AlpacaProvider`** (`data/alpaca_provider.py`): implements the Protocol using
  `alpaca-py`. Live 1-min bars via websocket; REST `get_recent_bars` for warmup.
- **Warmup:** at startup, REST-fetch the last ~60 bars per symbol so z-score/RSI are
  "hot" from the first live bar.
- **Feed:** `iex` (free) by default, configurable.

---

## 6. Anti-lookahead & correctness rules

- Signals are computed only on a **closed** bar (never mid-bar).
- **Debounce:** at most one signal event per symbol per closed bar; the same bar never
  re-triggers.
- All thresholds, the universe, and the feed come from `config.yaml` / `.env`. **No
  magic numbers in code.**
- **Timezone:** engine computes in UTC; terminal output additionally shows ET and
  Europe/Istanbul.

---

## 7. Persistence — signal tape

- `store/tape.py` appends one JSON object per signal evaluation to
  `logs/tape_YYYY-MM-DD.jsonl`.
- Event shape (minimum): `{ts_utc, symbol, close, z, rsi, regime, buy, sell}`.
- `logs/` is gitignored. (Full SQLite storage layer is Phase 3 — not here.)

---

## 8. Configuration & secrets

- `.env` (gitignored) holds `ALPACA_API_KEY`, `ALPACA_API_SECRET`,
  `ALPACA_PAPER_BASE_URL`, `ALPACA_DATA_FEED`. A committed `.env.example` documents them.
- `settings.py` loads `.env` via pydantic-settings.
- **Security:** the Alpaca keys shared during brainstorming are considered compromised
  and must be regenerated before use. Secrets never enter the repo.

---

## 9. Testing

Unit tests (pytest) for the pure functions, using synthetic DataFrames with
known-correct outputs:
- `indicators`: RSI/z-score/EMA/VWAP against hand-computed values.
- `spike_fade.generate`: a hand-built drop-reversal series MUST fire `buy`; a spike-
  reversal series MUST fire `sell`; a flat/noise series MUST fire neither.
- `regime.detect`: rising / falling / flat series classify as up / down / range.

No live-network tests in Phase 1; the live WS path is exercised manually against the DoD.

---

## 10. Technology

- Python 3.12, `alpaca-py`, `pandas`, `numpy`, `pydantic-settings`, `pyyaml`, `pytest`.
- `asyncio` for the websocket runner.

---

## 11. Out of scope (future phases)

- Phase 2: decision layer + option contract selection (regime-based suppression,
  spot/CALL/PUT matrix).
- Phase 2.5: catalyst gate + news provider (Ek-1).
- Phase 3: paper execution, portfolio, P&L, exit rules, SQLite, end-of-day report.
- Phase 4: FastAPI WS hub + React dashboard + TradingView widget + Telegram.
- Phase 5: TradingView webhook confirmation + live execution adapter (double-confirm).
```
