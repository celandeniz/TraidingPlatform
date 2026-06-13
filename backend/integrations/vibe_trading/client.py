"""VibeClient — synchronous HTTP transport to the Vibe-Trading sidecar.

Mirrors backend/research/ollama_client.py: a cheap health probe plus defensive
request helpers that NEVER raise into callers — every method returns a dict of
the shape {"ok": bool, ...} so the research/strategy/execution adapters and the
API endpoints can chain on `ok` and degrade cleanly when the container is down.

Capability methods (research, strategy, order proposals) are added on top of
these primitives in the per-purpose adapter modules.
"""
from __future__ import annotations

import json
from typing import Iterator, Optional

from .config import VibeConfig


class VibeClient:
    def __init__(self, config: VibeConfig):
        self._cfg = config

    @property
    def config(self) -> VibeConfig:
        return self._cfg

    # --- health -----------------------------------------------------------
    def health(self) -> dict:
        """Cheap up/down probe. Returns {"ok": bool, "detail": ...}."""
        try:
            import requests

            r = requests.get(
                self._cfg.url(self._cfg.health_path),
                headers=self._cfg.headers(),
                timeout=self._cfg.health_timeout,
            )
            r.raise_for_status()
            return {"ok": True, "status": r.status_code}
        except Exception as exc:  # noqa: BLE001 - container down / unreachable
            return {"ok": False, "detail": str(exc)}

    # --- request helpers (defensive; never raise) -------------------------
    def get_json(self, path: str, params: Optional[dict] = None) -> dict:
        return self._request("GET", path, params=params)

    def post_json(self, path: str, payload: Optional[dict] = None) -> dict:
        return self._request("POST", path, json_body=payload)

    def _request(self, method: str, path: str, *, params: Optional[dict] = None,
                 json_body: Optional[dict] = None) -> dict:
        try:
            import requests

            r = requests.request(
                method,
                self._cfg.url(path),
                params=params,
                json=json_body,
                headers=self._cfg.headers(),
                timeout=self._cfg.request_timeout,
            )
            r.raise_for_status()
            try:
                data = r.json()
            except ValueError:
                return {"ok": True, "raw": r.text}
            # Pass through Vibe's own ok flag if present; otherwise wrap.
            if isinstance(data, dict) and "ok" in data:
                return data
            return {"ok": True, "data": data}
        except Exception as exc:  # noqa: BLE001 - degrade, never crash the caller
            return {"ok": False, "detail": str(exc)}

    # --- session agent loop (Vibe's research + NL->strategy run here) ------
    # Vibe has no direct "research"/"backtest" REST call; both happen by sending
    # a natural-language message into a session and consuming the agent's events.
    def create_session(self, title: str = "TraidingPlatform",
                       config: Optional[dict] = None) -> dict:
        return self.post_json("/sessions", {"title": title, "config": config or {}})

    def send_message(self, session_id: str, content: str) -> dict:
        return self.post_json(f"/sessions/{session_id}/messages", {"content": content})

    def session_messages(self, session_id: str, limit: int = 50) -> dict:
        return self.get_json(f"/sessions/{session_id}/messages", {"limit": limit})

    def session_events(self, session_id: str) -> Iterator[dict]:
        """SSE stream of live agent events for a session (GET)."""
        return self.stream_sse(f"/sessions/{session_id}/events", method="GET")

    def get_run(self, run_id: str) -> dict:
        return self.get_json(f"/runs/{run_id}")

    def get_run_code(self, run_id: str) -> dict:
        return self.get_json(f"/runs/{run_id}/code")

    # --- SSE streaming (Vibe runs stream events on a long-lived response) --
    def stream_sse(self, path: str, payload: Optional[dict] = None,
                   method: str = "POST") -> Iterator[dict]:
        """Yield parsed SSE `data:` events as dicts. Yields a single
        {"ok": False, "detail": ...} event on transport failure rather than
        raising, so callers can iterate uniformly."""
        try:
            import requests

            with requests.request(
                method,
                self._cfg.url(path),
                json=payload,
                headers={**self._cfg.headers(), "Accept": "text/event-stream"},
                timeout=self._cfg.request_timeout,
                stream=True,
            ) as r:
                r.raise_for_status()
                for raw in r.iter_lines(decode_unicode=True):
                    if not raw or not raw.startswith("data:"):
                        continue
                    chunk = raw[len("data:"):].strip()
                    if not chunk or chunk == "[DONE]":
                        continue
                    try:
                        yield json.loads(chunk)
                    except ValueError:
                        yield {"event": "text", "data": chunk}
        except Exception as exc:  # noqa: BLE001
            yield {"ok": False, "detail": str(exc)}
