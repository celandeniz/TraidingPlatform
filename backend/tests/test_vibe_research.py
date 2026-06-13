"""Vibe research adapter tests — fake client, no network."""
from backend.integrations.vibe_trading import research_adapter as vr


class FakeClient:
    def __init__(self, *, session=None, sent=None, events=None, messages=None):
        self._session = session if session is not None else {"ok": True, "id": "s1"}
        self._sent = sent if sent is not None else {"ok": True}
        self._events = events or []
        self._messages = messages or {"ok": True, "data": []}

    def create_session(self, title="", config=None):
        return self._session

    def send_message(self, session_id, content):
        return self._sent

    def session_events(self, session_id):
        return iter(self._events)

    def session_messages(self, session_id, limit=50):
        return self._messages


def test_happy_path_bullish():
    events = [
        {"type": "token", "content": "Analyzing AAPL..."},
        {"type": "message", "content": "Strong bullish setup; buy on dips, upside ahead."},
        {"type": "done"},
    ]
    res = vr.run_research(FakeClient(events=events), "aapl")
    assert res.ok and res.symbol == "AAPL"
    assert res.side == "long" and res.confidence > 0
    assert "bullish" in res.summary.lower()


def test_bearish_verdict():
    events = [{"content": "Bearish; avoid, downside risk, sell.", "type": "final"}]
    res = vr.run_research(FakeClient(events=events), "tsla")
    assert res.side == "short"


def test_neutral_verdict():
    events = [{"content": "Mixed picture, no clear lean.", "type": "end"}]
    res = vr.run_research(FakeClient(events=events), "msft")
    assert res.side == "pass" and res.confidence == 0.0


def test_fallback_to_messages_when_events_empty():
    msgs = {"ok": True, "data": [{"role": "assistant", "content": "Bullish, long."}]}
    res = vr.run_research(FakeClient(events=[{"type": "done"}], messages=msgs), "nvda")
    assert res.ok and res.side == "long"


def test_session_creation_failure():
    res = vr.run_research(FakeClient(session={"ok": False, "detail": "down"}), "aapl")
    assert not res.ok and "down" in res.detail


def test_no_session_id():
    res = vr.run_research(FakeClient(session={"ok": True}), "aapl")
    assert not res.ok and "session id" in res.detail


def test_to_report_mapping():
    events = [{"content": "Bullish, buy, long, upside.", "type": "done"}]
    res = vr.run_research(FakeClient(events=events), "aapl")
    rep = vr.to_report(res)
    assert rep.role == "vibe_research" and rep.side == "long" and rep.available


def test_to_report_neutral_when_unavailable():
    res = vr.VibeResearchResult(False, "AAPL", detail="x")
    rep = vr.to_report(res)
    assert rep.side == "pass" and not rep.available
