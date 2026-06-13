"""Synthesis (NL->strategy compiler) tests — no LLM, no network.

Covers the dangerous machinery: validator, in-process harness backtest, the
subprocess sandbox isolation, the ranker (real tournament gates), the promoter,
the no-live-import guard, and the full pipeline with injected deps.
"""
import ast
import pathlib

import numpy as np
import pandas as pd
import pytest

from backend.synthesis import harness, pipeline, promoter, ranker
from backend.synthesis.brief import StrategyBrief
from backend.synthesis.generator import Candidate
from backend.synthesis.validator import validate_source

GOOD = """
class GenRsi:
    def evaluate(self, ctx):
        w = ctx.window
        if len(w) < 20:
            return StrategySignal(side=None)
        r = indicators.rsi(w["close"], 14)
        last = float(r.iloc[-1])
        if last < 35:
            return StrategySignal(side="buy", strength=0.5)
        if last > 65:
            return StrategySignal(side="sell", strength=0.5)
        return StrategySignal(side=None)
"""


def _df(n=400):
    idx = pd.date_range("2023-01-01", periods=n, freq="D", tz="UTC")
    t = np.arange(n)
    close = 100 + 10 * np.sin(t / 8.0) + np.sin(t / 3.0)  # oscillates -> RSI trades
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) + 0.5
    low = np.minimum(open_, close) - 0.5
    vol = np.full(n, 1_000_000.0)
    return pd.DataFrame({"open": open_, "high": high, "low": low,
                         "close": close, "volume": vol}, index=idx)


# --- validator ------------------------------------------------------------
def test_validator_accepts_good():
    ok, reason, name = validate_source(GOOD)
    assert ok and name == "GenRsi" and reason == ""


@pytest.mark.parametrize("bad,needle", [
    ("import os\nclass X:\n    def evaluate(self, ctx): return None", "imports"),
    ("class X:\n    def evaluate(self, ctx):\n        while True: pass", "while"),
    ("class X:\n    def evaluate(self, ctx): return open('x')", "open"),
    ("class X:\n    def evaluate(self, ctx): return self.__class__", "dunder"),
    ("class A:\n pass\nclass B:\n pass", "exactly one class"),
    ("class X:\n    def run(self, ctx): return None", "evaluate"),
    ("def f(): pass", "exactly one class"),
])
def test_validator_rejects(bad, needle):
    ok, reason, _ = validate_source(bad)
    assert not ok and needle in reason


# --- harness (in-process backtest) ----------------------------------------
def test_harness_runs_and_reports_metrics():
    m = harness.evaluate_candidate(GOOD, "GenRsi", _df(), config={}, warmup=20)
    assert "oos_sharpe" in m and "n_trades" in m
    assert m["n_trades"] > 0 and not m.get("error")


# --- sandbox (subprocess isolation) ---------------------------------------
def test_sandbox_good_candidate():
    from backend.synthesis.sandbox import run_candidate
    out = run_candidate(GOOD, "GenRsi", _df(200), warmup=20,
                        cpu_seconds=15, wall_seconds=30)
    assert out["ok"] is True and out["metrics"]["n_trades"] >= 0


def test_sandbox_kills_cpu_bomb():
    from backend.synthesis.sandbox import run_candidate
    bomb = ("class Bomb:\n"
            "    def evaluate(self, ctx):\n"
            "        s = 0\n"
            "        for i in range(10**12):\n"
            "            s += i\n"
            "        return StrategySignal(side=None)\n")
    out = run_candidate(bomb, "Bomb", _df(200), warmup=20,
                        cpu_seconds=1, wall_seconds=5)
    assert out["ok"] is False  # killed by CPU rlimit or wall-clock


# --- ranker (real tournament gates) ---------------------------------------
def test_ranker_gates_and_order():
    passing_metrics = {"max_drawdown_pct": 5.0, "profit_factor": 2.0,
                       "n_trades": 150, "significant": True, "oos_sharpe": 1.5}
    failing_metrics = {"max_drawdown_pct": 50.0, "profit_factor": 0.5,
                       "n_trades": 3, "significant": False, "oos_sharpe": 0.1}
    reports = ranker.rank([("good", passing_metrics), ("bad", failing_metrics)])
    assert reports[0].name == "good"
    passers = ranker.passing(reports)
    assert len(passers) == 1 and passers[0].name == "good"


# --- promoter (paper-only persistence) ------------------------------------
def test_promoter_writes_and_loads(tmp_path, monkeypatch):
    monkeypatch.setattr(promoter, "GEN_DIR", tmp_path / "gen")
    monkeypatch.setattr(promoter, "MANIFEST", tmp_path / "gen" / "manifest.json")
    out = promoter.promote("gen_aapl_0_GenRsi", GOOD, "GenRsi",
                           {"oos_sharpe": 1.0})
    assert out["ok"]
    loaded = promoter.load_promoted()
    assert "gen_aapl_0_genrsi" in loaded
    # the loaded class is instantiable and has evaluate
    inst = loaded["gen_aapl_0_genrsi"]()
    assert hasattr(inst, "evaluate")


# --- no-live-import guard -------------------------------------------------
def test_synthesis_never_imports_live_executor():
    pkg = pathlib.Path(promoter.__file__).parent
    offenders = []
    for py in pkg.glob("*.py"):
        tree = ast.parse(py.read_text())
        mods = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                mods.append(node.module or "")
        joined = " ".join(mods)
        if "execution.live" in joined or "build_live_executor" in py.read_text():
            offenders.append(py.name)
    assert offenders == [], f"synthesis must not reach live execution: {offenders}"


# --- pipeline (end-to-end, injected deps) ---------------------------------
class _Provider:
    def get_recent_bars(self, symbol, timeframe, bars):
        return _df(400)


def _inproc_backtest(source, class_name, df, *, config, warmup):
    """Deterministic in-process stand-in for the subprocess sandbox."""
    try:
        return {"ok": True, "metrics": harness.evaluate_candidate(
            source, class_name, df, config=config, warmup=warmup)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": str(exc)}


def test_pipeline_promotes_best(tmp_path, monkeypatch):
    monkeypatch.setattr(promoter, "GEN_DIR", tmp_path / "gen")
    monkeypatch.setattr(promoter, "MANIFEST", tmp_path / "gen" / "manifest.json")
    # Audit to tmp too.
    from backend.synthesis import audit
    monkeypatch.setattr(audit, "AUDIT_PATH", tmp_path / "audit.jsonl")
    # Force gates to pass so we exercise the promotion path deterministically.
    from backend.backtest.tournament import GateResult
    monkeypatch.setattr("backend.backtest.tournament.apply_gates",
                        lambda r: GateResult(passed=True))

    def fake_gen(brief, llm, n):
        return [Candidate(class_name="GenRsi", source=GOOD, index=i) for i in range(n)]

    brief = StrategyBrief.from_request("rsi reversion", symbol="AAPL", n_candidates=3)
    res = pipeline.synthesize(brief, settings=object(), cfg={}, llm=object(),
                              generator_fn=fake_gen, data_provider=_Provider(),
                              backtest_fn=_inproc_backtest)
    d = res.as_dict()
    assert d["ok"] and d["n_candidates"] == 3 and d["n_valid"] == 3
    assert d["source"] == "synthesis"
    assert d["n_passing"] == 3 and d["promoted"]  # best auto-promoted to paper


def test_pipeline_no_candidates_degrades(tmp_path, monkeypatch):
    from backend.synthesis import audit
    monkeypatch.setattr(audit, "AUDIT_PATH", tmp_path / "audit.jsonl")
    res = pipeline.synthesize(
        StrategyBrief.from_request("x"), settings=object(), cfg={}, llm=None,
        generator_fn=lambda b, l, n: [], data_provider=_Provider(),
        backtest_fn=_inproc_backtest)
    assert not res.ok and "no candidates" in res.detail
