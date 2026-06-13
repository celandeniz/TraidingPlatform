"""Vibe NL->strategy adapter tests — fake client, no network."""
from backend.integrations.vibe_trading import strategy_adapter as vs


class FakeClient:
    def __init__(self, *, session=None, sent=None, events=None, run=None, code=None):
        self._session = session if session is not None else {"ok": True, "id": "s1"}
        self._sent = sent if sent is not None else {"ok": True}
        self._events = events or []
        self._run = run or {"ok": True, "data": {"metrics": {"sharpe": 1.2}}}
        self._code = code or {"ok": True, "data": {"strategy.py": "print(1)"}}

    def create_session(self, title="", config=None):
        return self._session

    def send_message(self, session_id, content):
        return self._sent

    def session_events(self, session_id):
        return iter(self._events)

    def get_run(self, run_id):
        return self._run

    def get_run_code(self, run_id):
        return self._code


def test_happy_path_with_run():
    events = [
        {"type": "token", "content": "Writing strategy..."},
        {"type": "backtest", "run_id": "r42", "content": "Backtest complete."},
        {"type": "done"},
    ]
    res = vs.build_strategy(FakeClient(events=events), "fade gaps over 3%")
    d = res.as_dict()
    assert d["ok"] and d["run_id"] == "r42"
    assert d["metrics"] == {"sharpe": 1.2}
    assert d["code_files"] == {"strategy.py": "print(1)"}
    assert d["source"] == "vibe" and d["auto_promoted"] is False


def test_summary_only_no_run():
    events = [{"content": "Here is a strategy idea.", "type": "final"}]
    res = vs.build_strategy(FakeClient(events=events), "momentum on tech")
    assert res.ok and res.run_id == "" and res.summary


def test_empty_prompt_rejected():
    res = vs.build_strategy(FakeClient(), "   ")
    assert not res.ok and "empty" in res.detail


def test_session_failure():
    res = vs.build_strategy(FakeClient(session={"ok": False, "detail": "down"}), "x")
    assert not res.ok and "down" in res.detail


def test_no_output():
    res = vs.build_strategy(FakeClient(events=[{"type": "done"}]), "x")
    assert not res.ok and "no strategy output" in res.detail
