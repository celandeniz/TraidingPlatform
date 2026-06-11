# TraidingPlatform

Python/FastAPI trading research and execution control surface for the M7 strategy stack. The default configuration is safe: test profile, paper-style routing, no autonomous execution, and no live trading unless `LIVE_TRADING=true` is set intentionally.

The primary UI is now a Next.js + Tailwind + shadcn/ui app in `frontend/`. The original vanilla FastAPI dashboard is still available at `/legacy`.

## What It Includes

- Live / Signals dashboard with WebSocket price, signal, order, and position updates.
- OMS order ledger with stage, commit, push, fills, and transaction-cost analytics.
- Backtest runner, saved scenario browser, walk-forward validation, and regime-filter symbol selection.
- S&P 500 + NASDAQ-100 scanner with 5-minute buy-edge scores. Score is estimated edge, not a guarantee.
- Strategy tournament: 6 US-equity strategies (ORB, gap-and-go, cross-sectional momentum, sector rotation, earnings drift, pairs stat-arb) ranked by out-of-sample Sharpe behind hard risk gates, with a `/tournament` leaderboard.
- Unified news from Alpaca, RSS, and Yahoo, plus catalyst, sentiment, and LLM committee views.
- Optional LLM providers: Ollama, Claude, Gemini, DeepSeek, and OpenAI-compatible endpoints.
- Optional automation: scheduler, snapshots, reflection memory, auto-trader cycle, and Perspective live tables.
- Report export to Markdown, Word, and PDF when optional dependencies are installed.
- Setup page for test/live account profiles, feature flags, optional dependencies, and key-presence checks.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Fill `.env` with paper/test credentials first. Keep `.env` uncommitted.

## Run

```bash
# verify connectivity
.venv/bin/python -m backend.smoke_test

# run the CLI signal engine
.venv/bin/python -m backend.runner

# run the FastAPI API + legacy dashboard
.venv/bin/uvicorn backend.web.app:app --reload

# run the Next.js frontend
pnpm --dir frontend install
pnpm --dir frontend dev

# tests
.venv/bin/python -m pytest backend/tests/ -q
```

Frontend routes:

- `frontend/` Next.js app, defaults to `NEXT_PUBLIC_API_BASE=http://127.0.0.1:8765`
- `/live` Live / Signals
- `/positions` positions and OMS orders
- `/scanner` estimated-edge scanner
- `/tournament` strategy tournament leaderboard
- `/setup` setup and profiles

FastAPI legacy dashboard routes:

- `/legacy` main legacy dashboard
- `/setup` account profiles, feature flags, dependency/key presence
- `/perspective` optional Perspective live tables

## Configuration

Behavior lives in `backend/config.yaml`; credentials live in `.env`. `PROFILE=test` is the default profile. `PROFILE=live` applies live-profile risk/guard defaults, but real-money adapters still refuse to initialize unless `LIVE_TRADING=true`.

Important safe defaults:

- `LIVE_TRADING=false`
- `TRADING_MODE=paper`
- `auto_trader.enabled=false`
- `auto_trader.dry_run=true`
- `scanner.enabled=false` for the background loop; `/api/scan` remains on-demand
- `scheduler.enabled=false`
- `snapshots.enabled=false`
- `perspective.enabled=false`
- `reflection.enabled=false`
- `execution.realistic_fills=false`

Endpoints that report environment status return booleans for key presence only, never raw secret values.

## Development Notes

Add strategies by registering them in `backend/strategy/registry.py` and listing them under `strategies:` in `backend/config.yaml`. The FastAPI app keeps serving the JSON API, WebSocket, and legacy static UI; new UI work should live in `frontend/`.
