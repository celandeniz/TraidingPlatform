"""WebSocket origin allow-list (anti-CSWSH) — pure logic, no server needed."""
from backend.web.app import _ws_origin_ok


class _FakeWS:
    def __init__(self, origin=None):
        self.headers = {} if origin is None else {"origin": origin}


def test_no_origin_allowed():  # non-browser clients (CLI, tests) send no Origin
    assert _ws_origin_ok(_FakeWS(None)) is True


def test_localhost_origins_allowed():
    assert _ws_origin_ok(_FakeWS("http://localhost:8000")) is True
    assert _ws_origin_ok(_FakeWS("http://127.0.0.1:5173")) is True


def test_cross_site_origin_rejected():
    assert _ws_origin_ok(_FakeWS("https://evil.example.com")) is False
    # subdomain trick must not pass the host check
    assert _ws_origin_ok(_FakeWS("http://attacker.localhost.evil.com")) is False
