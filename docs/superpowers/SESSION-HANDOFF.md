# Session Handoff — continue on another machine

**Branch:** `feat/vibe-trading-integration` (cut from `feat/persona-panel`; intended PR base `feat/openalice-phase-a`).
**Last pushed:** see `git log -1` on origin; everything described here is committed + pushed unless noted under "In flight".

## What was built this session (all committed + pushed)
1. **Vibe-Trading sidecar integration** — `deploy/vibe-trading/` (Docker compose, off by default), `backend/integrations/vibe_trading/` (HTTP client, research/strategy adapters, OMS-routed `execution_router`). Endpoints `/api/vibe/*`. Vibe never trades directly; paper-mode-guarded.
2. **In-house NL→strategy compiler** — `backend/synthesis/` (brief→best-of-N LLM Python→AST validator→subprocess sandbox→tournament gates→auto-promote to paper). `POST /api/synthesis`. Spec: `docs/superpowers/specs/2026-06-13-nl-strategy-compiler-design.md`.
3. **Read-only Agent Gateway** — `backend/agent/gateway.py`, `POST /api/agent/gateway` (NL→tool dispatch→NL answer; never trades).
4. **Always-on paper auto-trader** — `backend/scripts/auto_trade_loop.py` (momentum-seeded, OMS-routed, paper-only).
5. **Backtest & Validation page** — tabbed `frontend/app/backtest/page.tsx` + 6 components in `frontend/components/core/backtest/`; backend `backend/backtest/run_one.py` + `/api/backtest` daily path across all generic strategies. Spec: `docs/superpowers/specs/2026-06-14-backtest-validation-page-design.md`; plan: `docs/superpowers/plans/2026-06-14-backtest-validation-page.md`.
6. **Frontend cards** for vibe research / synthesis / gateway on `/research`.

## Fixes this session
- Strategy correctness (Codex): earnings_drift lookahead, RSI flat-price, volume baseline.
- macOS LibreSSL cert bundle — `backend/__init__.py` sets `SSL_CERT_FILE`/`REQUESTS_CA_BUNDLE`/`CURL_CA_BUNDLE` to certifi (fixes Alpaca/yfinance SSLError).
- Frontend Next install was cross-linked to a sibling repo (`AIResources`) → isolated clean install, pinned Next `^15.5.0` (CVE-fixed).
- CORS allows any localhost dev port (`backend/web/app.py`) — fixed "failed to fetch".
- `/api/backtest` casts numpy scalars (was HTTP 500 on statistically-significant results).
- Test isolation: `test_vibe_execution_routing` uses a tmp ledger (no longer pollutes `logs/order_ledger.jsonl`).

## In flight (may be uncommitted locally — re-verify on the new machine)
- `backend/tests/test_daily_cache.py::test_get_fetches_once_then_serves_from_disk` is **date-brittle** (hardcodes `end=date(2026,6,10)`; the cache re-fetches once that's stale). A Codex fix to make it date-robust was in progress. If `git status` shows it modified/uncommitted, run `.venv/bin/python -m pytest backend/tests/test_daily_cache.py -q`; commit if green, else redo the fix (make the fake data's end the last completed business day relative to today; don't change `daily_cache.py` product logic).

## Open / next steps
- **Open the PR** (needs `gh auth login` or `GH_TOKEN`): base `feat/openalice-phase-a`, head `feat/vibe-trading-integration`. Compare URL: https://github.com/celandeniz/TraidingPlatform/compare/feat/openalice-phase-a...feat/vibe-trading-integration?expand=1
- Remaining "surface backend in UI" slices (each its own spec→plan→build): **Automation page + global kill switch**, **Reports page**, **Research additions** (committee/copilot/news cards).

## New-machine setup (these are NOT in git)
```bash
git clone https://github.com/celandeniz/TraidingPlatform.git && cd TraidingPlatform
git checkout feat/vibe-trading-integration
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # backend env
cp .env.example .env   # then fill Alpaca paper + LLM keys (NOT committed)
pnpm --dir frontend install                                          # frontend deps
# run:
.venv/bin/python -m uvicorn backend.web.app:app --port 8765         # API
pnpm --dir frontend dev                                              # UI (note the port it binds)
.venv/bin/python -m backend.scripts.auto_trade_loop --interval 900 --max-qty 5   # optional auto-trader
```
- Local-only (recreate, not in git): `.env`, `backend/.env`, `deploy/vibe-trading/agent.env`, `.venv`, `frontend/node_modules`, `backend/store/*` caches, `logs/`.
- Running processes from this machine are ephemeral — just relaunch on the new one.

## Environment caveats (carry over)
- Alpaca free IEX feed returns ~5 intraday bars → intraday backtests/scanner are data-starved; the **daily** path (yfinance `DailyBarCache`) works.
- LLM = local Ollama (slow). Gated-off features (vibe sidecar, snapshots, scheduler, perspective) return graceful `{ok/available:false}`.
