"""Orchestrate: brief -> generate N -> validate -> sandbox-backtest -> rank ->
promote best -> audit.

The single public entry point (synthesize) is dependency-injectable so it is
testable without an LLM, a data provider, or subprocesses: pass generator_fn,
data_provider, and/or backtest_fn. In production those default to the real
LLM best-of-N, the configured data provider, and the subprocess sandbox.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Callable, Optional

from . import audit, generator, promoter, ranker
from .brief import StrategyBrief
from .sandbox import run_candidate
from .validator import validate_source


@dataclass
class CandidateOutcome:
    name: str
    index: int
    valid: bool
    reason: str = ""
    metrics: dict = field(default_factory=dict)
    gates: dict = field(default_factory=dict)


@dataclass
class SynthesisResult:
    ok: bool
    symbol: str
    promoted: str = ""              # manifest key of the promoted strategy, or ""
    n_candidates: int = 0
    n_valid: int = 0
    n_passing: int = 0
    provider: str = ""
    outcomes: list = field(default_factory=list)
    detail: str = ""

    def as_dict(self) -> dict:
        d = asdict(self)
        d["source"] = "synthesis"
        return d


def _default_backtest(source, class_name, df, *, config, warmup):
    return run_candidate(source, class_name, df, config=config, warmup=warmup)


def synthesize(brief: StrategyBrief, *, settings, cfg: dict, llm=None,
               generator_fn: Optional[Callable] = None,
               data_provider=None,
               backtest_fn: Optional[Callable] = None,
               do_promote: bool = True) -> SynthesisResult:
    if llm is None:
        from ..research.llm_factory import build_llm_client
        llm = build_llm_client(settings, cfg)
    provider_name = type(llm).__name__ if llm is not None else "none"

    gen = generator_fn or generator.generate
    candidates = gen(brief, llm, brief.n_candidates)
    if not candidates:
        res = SynthesisResult(ok=False, symbol=brief.symbol, provider=provider_name,
                              detail="no candidates generated (LLM unavailable?)")
        audit.record({"event": "synthesis", **res.as_dict(), "brief": brief.text})
        return res

    # Market data once, shared across candidates.
    try:
        if data_provider is None:
            from ..brokers import build_data_provider
            data_provider = build_data_provider("equity", settings, cfg)
        df = data_provider.get_recent_bars(brief.symbol, brief.timeframe, brief.bars)
    except Exception as exc:  # noqa: BLE001
        res = SynthesisResult(ok=False, symbol=brief.symbol, provider=provider_name,
                              n_candidates=len(candidates),
                              detail=f"market data unavailable: {exc}")
        audit.record({"event": "synthesis", **res.as_dict(), "brief": brief.text})
        return res

    backtest = backtest_fn or _default_backtest

    outcomes: list[CandidateOutcome] = []
    named_metrics: list[tuple[str, dict]] = []
    for cand in candidates:
        name = f"gen_{brief.symbol.lower()}_{cand.index}_{cand.class_name}"
        ok, reason, class_name = validate_source(cand.source)
        if not ok:
            outcomes.append(CandidateOutcome(name, cand.index, False, reason=reason))
            continue
        bt = backtest(cand.source, class_name, df, config=cfg, warmup=35)
        if not bt.get("ok", False):
            outcomes.append(CandidateOutcome(name, cand.index, True,
                                             reason=bt.get("detail", "backtest failed")))
            continue
        metrics = bt.get("metrics", {})
        outcomes.append(CandidateOutcome(name, cand.index, True, metrics=metrics))
        named_metrics.append((name, metrics))

    reports = ranker.rank(named_metrics)
    by_name = {r.name: r for r in reports}
    for o in outcomes:
        rep = by_name.get(o.name)
        if rep and rep.gates:
            o.gates = rep.gates
    passing = ranker.passing(reports)

    promoted = ""
    if do_promote and passing:
        best = passing[0]
        cand = next(c for c in candidates
                    if f"gen_{brief.symbol.lower()}_{c.index}_{c.class_name}" == best.name)
        pr = promoter.promote(best.name, cand.source, cand.class_name,
                              best.metrics, brief_text=brief.text)
        if pr.get("ok"):
            promoted = pr["key"]

    res = SynthesisResult(
        ok=True, symbol=brief.symbol, promoted=promoted,
        n_candidates=len(candidates),
        n_valid=sum(1 for o in outcomes if o.valid),
        n_passing=len(passing), provider=provider_name,
        outcomes=[asdict(o) for o in outcomes],
        detail="" if promoted else "no candidate cleared the risk gates",
    )
    audit.record({"event": "synthesis", "brief": brief.text, "timeframe": brief.timeframe,
                  **res.as_dict()})
    return res
