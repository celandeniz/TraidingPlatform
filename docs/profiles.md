# Config Profiles

Profiles are named overlays in `backend/config.yaml`. The base config is loaded
first, then the active profile is deep-merged over it, so profile values win
without duplicating the whole file.

Activation order:

1. In-process web activation from `/setup`
2. `PROFILE` environment variable
3. `active_profile` in `backend/config.yaml`
4. `test`

If the `profiles` section is absent, config loading behaves as it did before.

## Defining A Profile

Add another entry under `profiles`:

```yaml
profiles:
  research-demo:
    name: research-demo
    mode: test
    broker: mock
    universe: [AAPL, MSFT]
    risk:
      enabled: false
    features:
      research: true
      committee: true
      auto_trader: false
      marketdata_backend: yahoo
      news_rss: true
      perspective: false
      reflection: false
      realistic_fills: false
```

Supported `mode` values are `test` and `live`. Supported broker values are
`alpaca_paper`, `alpaca_live`, `ccxt_sandbox`, `ccxt_live`, `mock`, and `ib`.
Unknown values fail startup with a clear `ValueError`.

## Test vs Live

The seeded `test` profile uses paper/sandbox style config, keeps risk and guards
off, and enables research only.

The seeded `live` profile marks the config as live, selects live broker metadata,
turns guards and `RiskManager` on, and keeps autonomous trading dry-run/off by
default. Selecting the `live` profile does not set `LIVE_TRADING`.

Real-money order flow remains gated by all existing controls:

- `LIVE_TRADING=true` in the environment
- Per-order confirmation in the live adapter
- Orders routed through `RiskManager`

## Setup Page

Open `/setup` from the dashboard Extras panel. It shows all profile names, the
active profile, feature toggles for the active config, optional dependency
availability, and whether expected env keys are set. The page reports booleans
only for keys and never returns secret values.
