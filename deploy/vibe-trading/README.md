# Vibe-Trading sidecar

Runs [HKUDS/Vibe-Trading](https://github.com/HKUDS/Vibe-Trading) as a containerized
sidecar that our platform consumes over HTTP. Vibe needs **Python 3.11+**; our backend
is **Python 3.9**, so Vibe is never installed in-process — it runs in its own container
and we talk to it on `127.0.0.1:8899`.

This is **Phase 0** of the integration (standalone + reachable). Backend wiring
(advisory, NL→strategy, OMS-routed execution) lands in later phases behind the
`vibe_trading:` config namespace in `backend/config.yaml` (default off).

## Pinned version

Vibe-Trading is an external, fast-moving project. Check out a known-good ref in your
clone and record it here so upgrades are deliberate:

- **Pinned ref:** `main @ <COMMIT_OR_TAG>` — _update when you bump it._

## Setup

```bash
# 1. Clone Vibe-Trading next to this repo (default location the compose expects).
#    Or set VIBE_TRADING_SRC to your clone path.
git clone https://github.com/HKUDS/Vibe-Trading.git ../Vibe-Trading

# 2. Create the sidecar env file (gitignored) and add ONE LLM provider key.
#    Add NO broker keys — see Safety below.
cp deploy/vibe-trading/agent.env.example deploy/vibe-trading/agent.env
$EDITOR deploy/vibe-trading/agent.env

# 3. Start it (from the repo root).
make vibe-up
```

## Make targets (from repo root)

| Target | Action |
|---|---|
| `make vibe-up`   | Start the sidecar (detached) on `127.0.0.1:8899`. |
| `make vibe-down` | Stop and remove the sidecar containers. |
| `make vibe-logs` | Tail sidecar logs. |
| `make vibe-ui`   | Start the sidecar **and** Vibe's own React UI on `127.0.0.1:5899`. |

All targets wrap `docker compose -f deploy/vibe-trading/docker-compose.yml`. If you
cloned Vibe-Trading somewhere else, prefix with `VIBE_TRADING_SRC=/path/to/Vibe-Trading`.

## Verify it's up

```bash
curl -s http://127.0.0.1:8899/health  # Vibe liveness probe
```

Once the backend phases land, set `vibe_trading.enabled: true` in
`backend/config.yaml`; the dashboard will show a `Vibe: up/down` status line and the
`/api/vibe/*` endpoints become live.

## Two NL→strategy surfaces (don't confuse them)

The platform has **two independent** natural-language → strategy paths. They never
import or share state with each other:

| | Our compiler (`/api/synthesis`) | Vibe sidecar (`/api/vibe/strategy`) |
|---|---|---|
| Engine | `backend/synthesis/` (spec'd, in-house) | HKUDS/Vibe-Trading container |
| Output | LLM→Python→AST-sandbox→backtest | Vibe agent writes + backtests code |
| Promotion | **Auto-promotes best to paper** (structurally paper-only) | **Never auto-promoted** — advisory/exploratory; `auto_promoted: false` |
| Result tag | n/a | `source: "vibe"` |

Use Vibe's path to explore ideas; use the in-house compiler when you want a result
that can actually reach the paper runner under the OMS/guard stack.

## Safety

- **No broker credentials in `agent.env`.** Vibe may only *propose* orders; proposals
  route back through our `Toolset.submit_order → OMS → guards → executor`, preserving the
  audit ledger, risk gates, and the live-trading hard-block. Vibe never trades directly.
- **Shell tools off** (`VIBE_TRADING_ENABLE_SHELL_TOOLS=0`) — they are an arbitrary-code
  surface inside the container.
- **Loopback only.** The port binds `127.0.0.1`; `VIBE_TRADING_TRUST_DOCKER_LOOPBACK=1`
  is safe only with that bind. Set `API_AUTH_KEY` before exposing `:8899` anywhere else.
- `deploy/vibe-trading/agent.env` is gitignored — only the `.example` is committed.
