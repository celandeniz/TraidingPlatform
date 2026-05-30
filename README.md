# M7 Spike-Fade — Phase 1 (Data + Signal Skeleton)

Live intraday signal engine for the Magnificent-7. Streams 1-minute bars from
Alpaca (paper), runs pluggable strategies, and logs every signal to the terminal
and a JSONL tape. **Phase 1 places no orders** — it detects and records signals.

See the design spec: `docs/superpowers/specs/2026-05-30-m7-spikefade-phase1-design.md`.

## Strategies (pluggable)

- **spike_fade** (signal): fade a sudden move once it reverses.
- **bollinger** (confirmation): multi-timeframe Bollinger Band confluence
  (`1m,3m,5m,15m,45m,1h`) grading each fired signal.

Add a strategy = implement a class, register a key in
`backend/strategy/registry.py`, list it under `strategies:` in
`backend/config.yaml`. No runner changes.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env        # then paste your Alpaca PAPER keys
```

## Run

```bash
# verify connectivity (account + recent bars, no streaming)
.venv/bin/python -m backend.smoke_test

# run the live signal engine (US session; Ctrl-C to stop)
.venv/bin/python -m backend.runner

# unit tests
.venv/bin/python -m pytest backend/tests/ -q
```

Signals stream to the terminal and append to `logs/tape_YYYY-MM-DD.jsonl`.

## Configuration

All thresholds live in `backend/config.yaml`; credentials in `.env` (never
committed). Engine computes in UTC; terminal shows ET + Istanbul time.
