from backend.research.catalyst_gate import evaluate


def test_earnings_today_suppresses():
    v = evaluate("buy", regime="range", news_ages_minutes=[], earnings_in_days=0,
                 gap_pct=None)
    assert v.verdict == "SUPPRESS"
    assert v.block_options is True


def test_hot_news_with_gap_suppresses():
    v = evaluate("sell", regime="range", news_ages_minutes=[5.0], earnings_in_days=None,
                 gap_pct=4.0, news_recency_minutes=30, gap_catalyst_pct=2.5)
    assert v.verdict == "SUPPRESS"


def test_hot_news_only_is_with_trend_only():
    v = evaluate("buy", regime="up", news_ages_minutes=[10.0], earnings_in_days=None,
                 gap_pct=0.5)
    assert v.verdict == "WITH_TREND_ONLY"


def test_big_gap_only_is_with_trend_only():
    v = evaluate("buy", regime="up", news_ages_minutes=[200.0], earnings_in_days=None,
                 gap_pct=3.0)
    assert v.verdict == "WITH_TREND_ONLY"


def test_quiet_allows():
    v = evaluate("buy", regime="range", news_ages_minutes=[300.0], earnings_in_days=None,
                 gap_pct=0.3)
    assert v.verdict == "ALLOW"
