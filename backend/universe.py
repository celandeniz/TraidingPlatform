"""Trading universe — resolve which symbols the platform watches/scans.

Beyond the original M7 list, the platform can load the S&P 500 and/or NASDAQ-100
constituents from bundled snapshots in backend/universe_data/ (sp500.json,
nasdaq100.json). The lists are static, version-controlled snapshots so resolution
is offline + deterministic; refresh them with scripts/refresh_universe.py.

Selection is config-driven (universe_mode) and always de-duplicated + sorted.
Falls back to the explicit config `universe:` list (M7) if a snapshot is missing,
so nothing breaks when the data files aren't present.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

UNIVERSE_DIR = Path(__file__).resolve().parent / "universe_data"

# universe_mode -> which snapshot files to union.
_MODE_FILES = {
    "m7": [],                                  # use the config `universe:` list
    "sp500": ["sp500.json"],
    "nasdaq100": ["nasdaq100.json"],
    "sp500_nasdaq100": ["sp500.json", "nasdaq100.json"],
}


@lru_cache
def _load_file(name: str) -> tuple:
    path = UNIVERSE_DIR / name
    if not path.exists():
        return tuple()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return tuple(str(s).strip().upper() for s in data if str(s).strip())
    except Exception:  # noqa: BLE001 - a corrupt snapshot must not break startup
        return tuple()


def load_universe(cfg: dict) -> list[str]:
    """Resolve the active universe from config.

    config keys:
      universe_mode: m7 | sp500 | nasdaq100 | sp500_nasdaq100 | custom  (default m7)
      universe:      explicit symbol list (the M7 default / custom list)
      universe_extra: optional extra symbols appended to any mode
    """
    mode = (cfg.get("universe_mode") or "m7").lower()
    base = [str(s).strip().upper() for s in (cfg.get("universe") or []) if str(s).strip()]

    if mode in ("m7", "custom"):
        symbols = list(base)
    else:
        files = _MODE_FILES.get(mode)
        if files is None:
            raise ValueError(f"unknown universe_mode: {mode}")
        symbols = []
        for f in files:
            symbols.extend(_load_file(f))
        if not symbols:  # snapshot missing/empty -> safe fallback to the config list
            symbols = list(base)

    symbols.extend(str(s).strip().upper() for s in (cfg.get("universe_extra") or [])
                   if str(s).strip())
    return sorted(set(symbols))


def universe_info(cfg: dict) -> dict:
    """Counts + source metadata for the setup/scan UI."""
    meta_path = UNIVERSE_DIR / "universe_meta.json"
    meta = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            meta = {}
    syms = load_universe(cfg)
    return {"mode": (cfg.get("universe_mode") or "m7").lower(),
            "count": len(syms), "meta": meta}
