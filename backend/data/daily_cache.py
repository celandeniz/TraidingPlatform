"""Daily OHLCV cache for the swing/portfolio strategies.

One CSV per symbol under the cache dir. Fetch is pluggable: pass fetch_fn
(symbol, start, end) -> DataFrame for tests; default tries Alpaca (alpaca-py)
then yfinance. Bars: open/high/low/close/volume, tz-aware UTC DatetimeIndex,
oldest..newest. Pure pandas otherwise — no network in tests.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

FetchFn = Callable[[str, date, date], pd.DataFrame]
COLUMNS = ["open", "high", "low", "close", "volume"]
TRADING_DAYS_PER_YEAR = 252


@dataclass
class CoverageReport:
    included: list = field(default_factory=list)
    excluded: dict = field(default_factory=dict)   # symbol -> reason


def _alpaca_creds() -> "tuple[str, str]":
    """Resolve Alpaca credentials the same way the rest of the app does:
    process env first (both APCA_* and ALPACA_* spellings), then the
    pydantic Settings object (which reads .env). Raises KeyError when no
    credentials exist anywhere — default_fetch treats that as "try yfinance"."""
    key = os.environ.get("APCA_API_KEY_ID") or os.environ.get("ALPACA_API_KEY")
    secret = (os.environ.get("APCA_API_SECRET_KEY")
              or os.environ.get("ALPACA_API_SECRET")
              or os.environ.get("ALPACA_SECRET_KEY"))
    if not (key and secret):
        try:
            from backend.settings import get_settings
            s = get_settings()
            key = key or s.alpaca_api_key
            secret = secret or s.alpaca_api_secret
        except Exception:  # noqa: BLE001 — settings optional in bare contexts
            pass
    if not (key and secret):
        raise KeyError("Alpaca credentials not found (ALPACA_API_KEY / ALPACA_API_SECRET)")
    return key, secret


def _fetch_alpaca(symbol: str, start: date, end: date) -> pd.DataFrame:
    key, secret = _alpaca_creds()
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    client = StockHistoricalDataClient(key, secret)
    req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Day,
                           start=start, end=end)
    bars = client.get_stock_bars(req).df
    if bars.empty:
        return pd.DataFrame(columns=COLUMNS)
    df = bars.reset_index().set_index("timestamp")[COLUMNS]
    return df.tz_convert("UTC") if df.index.tz else df.tz_localize("UTC")


def _fetch_yfinance(symbol: str, start: date, end: date) -> pd.DataFrame:
    import yfinance as yf

    raw = yf.download(symbol, start=start, end=end + timedelta(days=1),
                      auto_adjust=True, progress=False)
    if raw is None or raw.empty:
        return pd.DataFrame(columns=COLUMNS)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    df = raw.rename(columns=str.lower)[COLUMNS]
    return df.tz_localize("UTC") if df.index.tz is None else df.tz_convert("UTC")


def default_fetch(symbol: str, start: date, end: date) -> pd.DataFrame:
    """Alpaca primary, yfinance fallback (spec: Error Handling / data sources).

    Missing Alpaca credentials fall through to yfinance — verified live: the
    earlier raise-on-KeyError behavior made every keyless daily fetch fail
    instead of using the documented fallback. If yfinance is also missing,
    its ImportError propagates and the caller reports the symbol as excluded."""
    try:
        df = _fetch_alpaca(symbol, start, end)
        if not df.empty:
            return df
    except Exception:  # noqa: BLE001 — fall back to yfinance
        pass
    return _fetch_yfinance(symbol, start, end)


class DailyBarCache:
    def __init__(self, cache_dir: Path | str, fetch_fn: Optional[FetchFn] = None,
                 *, max_stale_days: int = 3):
        self.dir = Path(cache_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.fetch_fn = fetch_fn or default_fetch
        self.max_stale_days = max_stale_days

    def _path(self, symbol: str) -> Path:
        safe = symbol.upper().replace("/", "_").replace("..", "__")
        return self.dir / f"{safe}.csv"

    def _load(self, symbol: str) -> Optional[pd.DataFrame]:
        p = self._path(symbol)
        if not p.exists():
            return None
        df = pd.read_csv(p, index_col=0, parse_dates=True)
        if df.empty:
            return None  # empty CSV = cache miss → refetch
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        return df[COLUMNS]

    def _save(self, symbol: str, df: pd.DataFrame) -> None:
        df.to_csv(self._path(symbol))

    def get(self, symbol: str, *, years: int = 5) -> pd.DataFrame:
        """Cached daily bars, refreshed incrementally when stale.

        ``years`` controls the initial fetch window only; once the cache file
        exists, the full cached history is returned (and extended incrementally).
        """
        today = date.today()
        df = self._load(symbol)
        if df is None or df.empty:
            df = self.fetch_fn(symbol, today - timedelta(days=int(years * 365.25)), today)
            df = self._normalize(df)
            self._save(symbol, df)
            return df
        last = df.index.max().date()
        if (today - last).days > self.max_stale_days:
            fresh = self._normalize(self.fetch_fn(symbol, last, today))
            if not fresh.empty:
                df = pd.concat([df, fresh])
                df = df[~df.index.duplicated(keep="last")].sort_index()
                self._save(symbol, df)
        return df

    @staticmethod
    def _normalize(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return pd.DataFrame(columns=COLUMNS)
        df = df[COLUMNS].sort_index()
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        elif str(df.index.tz) != "UTC":
            df.index = df.index.tz_convert("UTC")
        return df[~df.index.duplicated(keep="last")]

    def ensure(self, symbols: list[str], *, years: int = 5,
               min_years: int = 3) -> CoverageReport:
        """Backfill all symbols; exclude (with reason) any below min coverage.
        Spec rule: never silently dropped."""
        rep = CoverageReport()
        need = min_years * TRADING_DAYS_PER_YEAR
        for sym in symbols:
            try:
                df = self.get(sym, years=years)
            except Exception as exc:           # noqa: BLE001 — reported, not hidden
                rep.excluded[sym] = f"fetch failed: {exc}"
                continue
            if len(df) < need:
                rep.excluded[sym] = f"insufficient history: {len(df)} rows < {need}"
            else:
                rep.included.append(sym)
        return rep
