"""Strategy registry: string key -> strategy class.

The runner instantiates only the strategies named in config.yaml. To add a new
strategy: implement it, add it to one of the maps below, and list its key under
`strategies:` in config.yaml. No runner changes required.
"""
from __future__ import annotations

from .atr_trend import AtrTrendStrategy
from .base import ConfirmationStrategy, SignalStrategy
from .bollinger_confluence import BollingerConfluenceStrategy
from .donchian_breakout import DonchianBreakoutStrategy
from .ema_momentum import EmaMomentumStrategy
from .keltner_breakout import KeltnerBreakoutStrategy
from .macd_cross import MacdCrossStrategy
from .gap_go import GapGoStrategy
from .orb_breakout import OrbBreakoutStrategy
from .rsi_reversion import RsiReversionStrategy
from .sector_rotation import SectorRotationStrategy
from .spike_fade import SpikeFadeStrategy
from .volume_confirm import VolumeConfirmStrategy
from .vwap_reversion import VwapReversionStrategy
from .xs_momentum import XsMomentumStrategy

SIGNAL_STRATEGIES: dict[str, type] = {
    "spike_fade": SpikeFadeStrategy,
    "ema_momentum": EmaMomentumStrategy,
    "donchian_breakout": DonchianBreakoutStrategy,
    "rsi_reversion": RsiReversionStrategy,
    "macd_cross": MacdCrossStrategy,
    "vwap_reversion": VwapReversionStrategy,
    "keltner_breakout": KeltnerBreakoutStrategy,
    "atr_trend": AtrTrendStrategy,
    "orb_breakout": OrbBreakoutStrategy,
    "gap_go": GapGoStrategy,
}

CONFIRMATION_STRATEGIES: dict[str, type] = {
    "bollinger": BollingerConfluenceStrategy,
    "volume": VolumeConfirmStrategy,
}

# Daily-bar cross-sectional strategies (tournament / portfolio engine — not the
# 1m signal runner).
PORTFOLIO_STRATEGIES: dict[str, type] = {
    "xs_momentum": XsMomentumStrategy,
    "sector_rotation": SectorRotationStrategy,
}


def build_signal_strategies(config: dict) -> list[SignalStrategy]:
    keys = config.get("strategies", {}).get("signal", [])
    return [_make(SIGNAL_STRATEGIES, k, "signal") for k in keys]


def build_confirmation_strategies(config: dict) -> list[ConfirmationStrategy]:
    keys = config.get("strategies", {}).get("confirmations", [])
    return [_make(CONFIRMATION_STRATEGIES, k, "confirmation") for k in keys]


def build_generated_signal_strategies() -> list:
    """Instantiate promoted (LLM-generated) strategies from the synthesis manifest.

    Best-effort and isolated: a bad/missing entry is skipped. Each instance is
    tagged _generated and given a .name so the runner's regime filter works.
    These are paper-only by construction (see backend/synthesis/promoter.py).
    """
    try:
        from ..synthesis.promoter import load_promoted
    except Exception:  # noqa: BLE001 - synthesis optional
        return []
    out = []
    for key, cls in load_promoted().items():
        try:
            inst = cls()
            if not getattr(inst, "name", None):
                inst.name = key
            inst._generated = True
            out.append(inst)
        except Exception:  # noqa: BLE001 - skip a bad class, keep the rest
            continue
    return out


def _make(registry: dict[str, type], key: str, kind: str):
    if key not in registry:
        raise KeyError(
            f"Unknown {kind} strategy '{key}'. "
            f"Registered: {sorted(registry)}"
        )
    return registry[key]()
