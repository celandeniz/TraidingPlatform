"""External-service integrations consumed by this platform.

Each integration runs as a separate process/service (our backend never imports
a third-party trading platform in-process) and is reached over HTTP behind a
config-gated, graceful-degrade-to-None builder — the same pattern as
backend/marketdata and backend/research.
"""
