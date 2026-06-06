"""Reflection-memory tests — no network (fake LLM / heuristic)."""
from datetime import datetime, timezone

from backend.research.reflection import ReflectionMemory, TradeClosure

UTC = timezone.utc


def _closure(symbol="AAPL", ret=1.5, reason="take_profit", side="long"):
    return TradeClosure(symbol=symbol, side=side, entry=100, exit=100 * (1 + ret / 100),
                        ret_pct=ret, opened_at="t0", closed_at="t1", exit_reason=reason,
                        regime="range", rationale="mean-reversion fade")


class _FakeLLM:
    def structured(self, **kw):
        return {"tag": "win", "lesson": "fades in range worked; keep tight stop"}


def test_heuristic_lesson_without_llm(tmp_path):
    mem = ReflectionMemory(path=tmp_path / "r.jsonl", use_llm=False,
                           clock=lambda: datetime(2024, 1, 1, tzinfo=UTC))
    note = mem.record_closure(_closure(ret=2.0))
    assert note["tag"] == "win" and "take_profit" in note["lesson"]
    loss = mem.record_closure(_closure(ret=-1.0, reason="stop_loss"))
    assert loss["tag"] == "loss"


def test_llm_lesson_when_enabled(tmp_path):
    mem = ReflectionMemory(path=tmp_path / "r.jsonl", llm=_FakeLLM(), use_llm=True)
    note = mem.record_closure(_closure())
    assert note["tag"] == "win" and "tight stop" in note["lesson"]


def test_recent_filters_by_symbol(tmp_path):
    mem = ReflectionMemory(path=tmp_path / "r.jsonl", use_llm=False)
    mem.record_closure(_closure(symbol="AAPL"))
    mem.record_closure(_closure(symbol="MSFT"))
    assert {n["symbol"] for n in mem.recent()} == {"AAPL", "MSFT"}
    assert [n["symbol"] for n in mem.recent(symbol="aapl")] == ["AAPL"]


def test_notes_text_digest(tmp_path):
    mem = ReflectionMemory(path=tmp_path / "r.jsonl", use_llm=False)
    assert mem.notes_text() == ""  # empty when no notes
    mem.record_closure(_closure())
    txt = mem.notes_text(symbol="AAPL")
    assert "Past lessons:" in txt and "AAPL" in txt


def test_manager_close_triggers_reflection(tmp_path):
    # End-to-end: PositionManager close -> reflection record (opt-in via param).
    from datetime import datetime as _dt

    from backend.execution.mock_adapter import MockExecutionAdapter
    from backend.portfolio.manager import ExitConfig, PositionManager
    from backend.research.base import Decision

    broker = MockExecutionAdapter(starting_cash=100_000)
    broker.mark("AAPL", 100)
    mem = ReflectionMemory(path=tmp_path / "r.jsonl", use_llm=False)
    clock = lambda: _dt(2024, 1, 1, 15, 0, tzinfo=UTC)
    mgr = PositionManager(broker, clock=clock,
                          market_is_closing=lambda now, m: False,
                          exit_cfg=ExitConfig(take_profit_pct=1.0, stop_loss_pct=1.0,
                                              trailing_stop_pct=None, time_stop_minutes=None),
                          reflection=mem)
    dec = Decision("AAPL", "SPOT_LONG", "ALLOW", "buy", rationale="fade", confirmations={})
    mgr.open_from_decision(dec, mark=100, qty=10)
    broker.mark("AAPL", 102)            # +2% -> take-profit (>=1%)
    res = mgr.manage("AAPL", 102)
    assert res is not None and res.ok
    notes = mem.recent(symbol="AAPL")
    assert len(notes) == 1 and notes[0]["exit_reason"] == "take_profit"
    assert notes[0]["rationale"] == "fade"  # original thesis carried through tags
