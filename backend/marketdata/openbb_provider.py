"""OpenBB-backed MarketDataProvider.

Wraps the upstream OpenBB Python SDK (``from openbb import obb``). Heavy import is
deferred to first use so the test suite and the live runner never pay for it
unless market data is actually requested. Every call is defensive: provider
hiccups degrade to an empty frame / sparse Fundamentals rather than crashing the
caller.

Clean-room: written against public OpenBB docs, not from OpenAlice source.
"""
from __future__ import annotations

from typing import Literal, Optional

import pandas as pd

from .base import AssetKind, Fundamentals, MarketDataProvider, SymbolMatch

# OpenBB interval tokens differ slightly from our "1m/5m/1d" convention; map ours -> theirs.
_INTERVAL = {
    "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
    "45m": "45m", "1h": "1h", "1d": "1d", "1w": "1W", "1M": "1M",
}


class OpenBBProvider:
    """A thin, defensive adapter over the OpenBB Platform Python SDK."""

    def __init__(self, providers: Optional[dict] = None, api_keys: Optional[dict] = None):
        # providers: optional per-asset default provider, e.g. {"equity": "fmp"}
        self._providers = providers or {}
        self._api_keys = api_keys or {}
        self._obb = None

    def _client(self):
        if self._obb is not None:
            return self._obb
        from openbb import obb  # lazy: only when market data is used

        # Register any API keys at runtime (no global config files needed).
        for name, key in self._api_keys.items():
            if not key:
                continue
            try:
                setattr(obb.user.credentials, name, key)
            except Exception:  # noqa: BLE001 - unknown credential names shouldn't crash
                pass
        self._obb = obb
        return obb

    @staticmethod
    def _to_df(output) -> pd.DataFrame:
        """Normalize any OBBject to a DataFrame, tolerating SDK version differences."""
        for attr in ("to_dataframe", "to_df"):
            fn = getattr(output, attr, None)
            if callable(fn):
                try:
                    return fn()
                except Exception:  # noqa: BLE001
                    break
        results = getattr(output, "results", output)
        try:
            return pd.json_normalize([r.model_dump() if hasattr(r, "model_dump") else r
                                      for r in results])
        except Exception:  # noqa: BLE001
            return pd.DataFrame()

    def _provider_for(self, kind: AssetKind):
        p = self._providers.get(kind)
        return {"provider": p} if p else {}

    # --- MarketDataProvider --------------------------------------------------
    def get_recent_bars(self, symbol: str, timeframe: str = "1d", lookback: int = 250,
                         kind: AssetKind = "equity") -> pd.DataFrame:
        obb = self._client()
        interval = _INTERVAL.get(timeframe, timeframe)
        route = {
            "equity": lambda: obb.equity.price.historical(symbol, interval=interval, **self._provider_for("equity")),
            "crypto": lambda: obb.crypto.price.historical(symbol, interval=interval, **self._provider_for("crypto")),
            "currency": lambda: obb.currency.price.historical(symbol, interval=interval, **self._provider_for("currency")),
            "index": lambda: obb.index.price.historical(symbol, interval=interval, **self._provider_for("index")),
        }.get(kind, lambda: obb.equity.price.historical(symbol, interval=interval, **self._provider_for("equity")))
        try:
            df = self._to_df(route())
        except Exception:  # noqa: BLE001
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        if df.empty:
            return df
        if "date" in df.columns:
            df = df.set_index("date")
        keep = [c for c in ("open", "high", "low", "close", "volume") if c in df.columns]
        return df[keep].tail(lookback)

    def search_symbols(self, query: str, kind: Optional[AssetKind] = None) -> list[SymbolMatch]:
        obb = self._client()
        try:
            df = self._to_df(obb.equity.search(query))
        except Exception:  # noqa: BLE001
            return []
        out: list[SymbolMatch] = []
        for _, row in df.iterrows():
            d = row.to_dict()
            out.append(SymbolMatch(
                symbol=str(d.get("symbol") or d.get("ticker") or ""),
                name=str(d.get("name") or ""),
                kind=kind or "equity",
                exchange=str(d.get("exchange") or d.get("cik") or ""),
                extra=d,
            ))
        return [m for m in out if m.symbol]

    def get_fundamentals(self, symbol: str) -> Fundamentals:
        obb = self._client()
        f = Fundamentals(symbol=symbol)
        try:
            prof = self._to_df(obb.equity.profile(symbol, **self._provider_for("equity")))
            if not prof.empty:
                p = prof.iloc[0].to_dict()
                f.name = p.get("name")
                f.sector = p.get("sector")
                f.industry = p.get("industry")
                f.market_cap = _num(p.get("market_cap"))
                f.raw["profile"] = p
        except Exception:  # noqa: BLE001
            pass
        try:
            ratios = self._to_df(obb.equity.fundamental.ratios(symbol, limit=1, **self._provider_for("equity")))
            if not ratios.empty:
                r = ratios.iloc[-1].to_dict()
                f.pe_ratio = _num(r.get("price_to_earnings") or r.get("pe_ratio"))
                f.debt_to_equity = _num(r.get("debt_to_equity"))
                f.profit_margin = _num(r.get("net_profit_margin") or r.get("profit_margin"))
                f.raw["ratios"] = r
        except Exception:  # noqa: BLE001
            pass
        return f

    def get_earnings_calendar(self, start: Optional[str] = None, end: Optional[str] = None) -> pd.DataFrame:
        obb = self._client()
        try:
            kw = {}
            if start:
                kw["start_date"] = start
            if end:
                kw["end_date"] = end
            return self._to_df(obb.equity.calendar.earnings(**kw))
        except Exception:  # noqa: BLE001
            return pd.DataFrame()

    def get_insider_trading(self, symbol: str, limit: int = 100) -> pd.DataFrame:
        obb = self._client()
        try:
            return self._to_df(obb.equity.ownership.insider_trading(symbol, limit=limit,
                                                                    **self._provider_for("equity")))
        except Exception:  # noqa: BLE001
            return pd.DataFrame()

    def get_market_movers(self, kind: Literal["gainers", "losers", "active"] = "gainers") -> pd.DataFrame:
        obb = self._client()
        route = {
            "gainers": lambda: obb.equity.discovery.gainers(),
            "losers": lambda: obb.equity.discovery.losers(),
            "active": lambda: obb.equity.discovery.active(),
        }.get(kind, lambda: obb.equity.discovery.gainers())
        try:
            return self._to_df(route())
        except Exception:  # noqa: BLE001
            return pd.DataFrame()


def _num(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
