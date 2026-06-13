"""TraidingPlatform backend package.

Ensure a valid CA bundle is configured before any networking import. On macOS the
stock Python links LibreSSL, which doesn't know where certs live, so requests /
yfinance (curl_cffi) fail with SSLError(_ssl.c) / curl(77) CAfile errors. Point
the standard env vars at certifi's bundle unless the user already set them.
"""
import os as _os

try:
    import certifi as _certifi

    _bundle = _certifi.where()
    for _var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        _os.environ.setdefault(_var, _bundle)
except Exception:  # noqa: BLE001 - certifi optional; fall back to system defaults
    pass
