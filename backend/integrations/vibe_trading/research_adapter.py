"""Vibe research/advisory adapter.

Vibe has no one-shot "research" REST call: research runs as an agent loop inside a
session (create session -> send a NL message -> consume SSE events). This module
drives that flow and normalizes the result into a small, UI/committee-friendly
shape. It NEVER touches the trading path.

The exact SSE event schema is Vibe-internal and may change, so text/verdict
extraction is intentionally defensive: unknown shapes degrade to an empty summary
and a neutral ("pass") vote rather than raising. Refine _extract_text / _verdict
once the event contract is pinned (see deploy/vibe-trading/README pin note).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Event "type"/"status" values we treat as end-of-run.
_TERMINAL = {"done", "complete", "completed", "final", "finished", "end",
             "run_complete", "goal_complete", "error", "cancelled", "canceled"}
# Keys that may carry assistant text inside an event.
_TEXT_KEYS = ("content", "text", "message", "delta", "answer", "summary")

_BULL = ("bullish", "buy", "long", "overweight", "accumulate", "upside")
_BEAR = ("bearish", "sell", "short", "underweight", "downside", "avoid")


@dataclass
class VibeResearchResult:
    ok: bool
    symbol: str
    summary: str = ""
    side: str = "pass"          # long | short | pass
    confidence: float = 0.0     # 0..1 (heuristic from the summary text)
    session_id: str = ""
    events: int = 0
    detail: str = ""

    def as_dict(self) -> dict:
        return {
            "ok": self.ok, "symbol": self.symbol, "summary": self.summary,
            "side": self.side, "confidence": self.confidence,
            "session_id": self.session_id, "events": self.events,
            "detail": self.detail, "source": "vibe",
        }


def _dig_id(payload: dict) -> str:
    """Pull a session id out of Vibe's create-session response, defensively."""
    for container in (payload, payload.get("data") or {}):
        if not isinstance(container, dict):
            continue
        for k in ("id", "session_id", "sessionId"):
            v = container.get(k)
            if v:
                return str(v)
    return ""


def _extract_text(event: dict) -> str:
    """Best-effort assistant text from one SSE event."""
    parts = []
    for k in _TEXT_KEYS:
        v = event.get(k)
        if isinstance(v, str) and v.strip():
            parts.append(v.strip())
        elif isinstance(v, dict):
            # e.g. {"message": {"content": "..."}}
            inner = v.get("content") or v.get("text")
            if isinstance(inner, str) and inner.strip():
                parts.append(inner.strip())
    return " ".join(parts)


def _is_terminal(event: dict) -> bool:
    for k in ("type", "event", "status", "state"):
        val = str(event.get(k, "")).lower()
        if val in _TERMINAL:
            return True
    return False


def _verdict(text: str) -> tuple[str, float]:
    """Coarse directional read of the summary. Heuristic, capped confidence."""
    low = text.lower()
    bull = sum(low.count(w) for w in _BULL)
    bear = sum(low.count(w) for w in _BEAR)
    if bull == bear:
        return "pass", 0.0
    side = "long" if bull > bear else "short"
    lead = abs(bull - bear)
    return side, min(0.6, 0.2 + 0.1 * lead)  # never overconfident on keywords


def default_prompt(symbol: str) -> str:
    return (f"Give a concise investment research summary for {symbol}: key drivers, "
            f"risks, and an overall bullish/bearish lean. Keep it under 200 words.")


def run_research(client, symbol: str, *, prompt: Optional[str] = None,
                 max_events: int = 300) -> VibeResearchResult:
    """Drive a Vibe session to research `symbol` and return a normalized result."""
    sym = symbol.upper()
    sess = client.create_session(title=f"research:{sym}")
    if not sess.get("ok", False):
        return VibeResearchResult(False, sym, detail=sess.get("detail", "session failed"))
    session_id = _dig_id(sess)
    if not session_id:
        return VibeResearchResult(False, sym, detail="no session id in response")

    sent = client.send_message(session_id, prompt or default_prompt(sym))
    if not sent.get("ok", False):
        return VibeResearchResult(False, sym, session_id=session_id,
                                  detail=sent.get("detail", "send failed"))

    chunks: list[str] = []
    count = 0
    for event in client.session_events(session_id):
        count += 1
        if not isinstance(event, dict):
            continue
        if event.get("ok") is False:  # transport error event from the client
            break
        text = _extract_text(event)
        if text:
            chunks.append(text)
        if _is_terminal(event) or count >= max_events:
            break

    summary = chunks[-1] if chunks else ""
    # Fall back to the message history if the stream gave us nothing usable.
    if not summary:
        hist = client.session_messages(session_id)
        msgs = hist.get("data") if isinstance(hist.get("data"), list) else hist.get("messages")
        if isinstance(msgs, list):
            for m in reversed(msgs):
                t = _extract_text(m) if isinstance(m, dict) else ""
                if t:
                    summary = t
                    break

    side, conf = _verdict(summary)
    return VibeResearchResult(
        ok=bool(summary), symbol=sym, summary=summary, side=side, confidence=conf,
        session_id=session_id, events=count,
        detail="" if summary else "no assistant text produced",
    )


def to_report(result: VibeResearchResult):
    """Map a research result to ONE committee AnalystReport (optional hook)."""
    from ...research.base import AnalystReport

    return AnalystReport(
        role="vibe_research",
        side=result.side if result.side in ("long", "short", "pass") else "pass",
        confidence=float(result.confidence),
        rationale=(result.summary[:400] or "vibe research unavailable"),
        available=result.ok,
    )
