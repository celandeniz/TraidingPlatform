"""Committee tests with a MOCKED client (no network, no anthropic import)."""
from backend.research.agents.committee import run_committee
from backend.research.agents.debate import run_debate
from backend.research.base import CatalystVerdict, CommitteeVerdict
from backend.research.decision_layer import decide
from backend.research.llm import CostCapExceeded


class SeqClient:
    """Returns canned payloads in order; counts calls; records kwargs."""

    def __init__(self, payloads, raise_on=None, exc=CostCapExceeded):
        self.payloads = list(payloads)
        self.calls = 0
        self.kwargs_log = []
        self._raise_on = raise_on
        self._exc = exc
        self.spent_usd = 0.0

    def structured(self, **kwargs):
        self.calls += 1
        self.kwargs_log.append(kwargs)
        if self._raise_on is not None and self.calls == self._raise_on:
            raise self._exc("simulated")
        self.spent_usd += 0.001
        return self.payloads.pop(0) if self.payloads else {}


def _vote(side, conf=0.7):
    return {"side": side, "confidence": conf, "rationale": "r"}


def _debate():
    return {"argument": "a", "strongest_point": "p"}


def _trade(side, conf=0.7):
    return {"side": side, "confidence": conf, "rationale": "r", "key_risk": "k"}


def _gate():
    return CatalystVerdict(verdict="ALLOW", reasons=["clear"])


def _full_run_payloads(rounds=1, final="long", n_analysts=6):
    # 6 analysts when headlines present: 4 personas + news_technical + sentiment_news
    return ([_vote("long")] * n_analysts + [_debate()] * (2 * rounds) + [_trade(final)])


def test_committee_full_pipeline_call_budget():
    rounds = 1
    c = SeqClient(_full_run_payloads(rounds, "long"))
    v = run_committee(c, "TSLA", "buy", context="ctx", headlines=["h"],
                      gate=_gate(), bb_meta={"bb_score": 2}, cfg={"debate_rounds": rounds})
    assert v.available is True
    assert v.side == "long"
    # 6 analysts (incl. dedicated sentiment_news) + debate + trader (risk is python)
    assert c.calls == 6 + 2 * rounds + 1
    assert v.rounds_run == rounds


def test_debate_message_is_O1_not_full_transcript():
    c = SeqClient([_debate()] * 4)
    run_debate(c, "X", side="buy", analyst_digest="DIGEST", max_rounds=2)
    for kw in c.kwargs_log:
        assert "DIGEST" in kw["system"]            # digest cached in system block
        assert "DIGEST" not in kw["user"]          # not duplicated per-turn
        assert kw["user"].count("Opponent's last argument") <= 1


def test_debate_round_hard_cap():
    c = SeqClient([_debate()] * 20)
    turns = run_debate(c, "X", side="buy", analyst_digest="d", max_rounds=99)
    assert len(turns) == 2 * 3  # clamped to ROUND_HARD_CAP=3


def test_committee_degrades_on_cost_cap():
    # Analysts (calls 1-5) swallow errors individually; cost cap surfaces at the
    # debate stage (call 6) and propagates -> available False, analysts preserved.
    c = SeqClient([_vote("long")] * 5, raise_on=6)
    v = run_committee(c, "X", "buy", context="c", headlines=[], gate=_gate(),
                      bb_meta={}, cfg={"debate_rounds": 1, "fallback_to_consensus": False})
    assert v.available is False
    assert "simulated" in v.error
    assert len(v.analyst_reports) == 5


# ---- decision_layer committee modes ---------------------------------------
def _committee(side, conf, available=True):
    return CommitteeVerdict(symbol="X", side=side, confidence=conf,
                            rationale="r", available=available)


def test_committee_off_is_no_op():
    d = decide("X", "buy", tier="high_vol", regime="range", gate=_gate(),
               committee=_committee("short", 0.9), committee_mode="off")
    assert d.action == "CALL"
    assert "committee" not in d.confirmations


def test_committee_confirm_attaches_no_action_change():
    d = decide("X", "buy", tier="high_vol", regime="range", gate=_gate(),
               committee=_committee("short", 0.9), committee_mode="confirm")
    assert d.action == "CALL"
    assert d.confirmations["committee"]["side"] == "short"


def test_committee_veto_blocks_opposing():
    d = decide("X", "buy", tier="high_vol", regime="range", gate=_gate(),
               committee=_committee("short", 0.8), committee_mode="veto",
               committee_veto_confidence=0.6)
    assert d.action == "NONE" and "veto" in d.rationale


def test_committee_veto_ignores_low_confidence():
    d = decide("X", "buy", tier="high_vol", regime="range", gate=_gate(),
               committee=_committee("short", 0.3), committee_mode="veto",
               committee_veto_confidence=0.6)
    assert d.action == "CALL"


def test_committee_decide_drives_side():
    d = decide("X", "sell", tier="high_vol", regime="range", gate=_gate(),
               committee=_committee("short", 0.7), committee_mode="decide")
    assert d.action == "PUT"


def test_gate_suppress_wins_over_bullish_committee():
    g = CatalystVerdict(verdict="SUPPRESS", reasons=["earnings"])
    d = decide("X", "buy", tier="high_vol", regime="range", gate=g,
               committee=_committee("long", 0.99), committee_mode="decide")
    assert d.action == "NONE" and "catalyst" in d.rationale
