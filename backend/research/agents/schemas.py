"""JSON tool-schemas for the committee stages (forced structured output)."""
from __future__ import annotations

DEBATE_SCHEMA = {
    "type": "object",
    "properties": {
        "argument": {"type": "string", "description": "<=3 sentences arguing your side"},
        "strongest_point": {"type": "string", "description": "your single best point"},
    },
    "required": ["argument", "strongest_point"],
}

TRADER_SCHEMA = {
    "type": "object",
    "properties": {
        "side": {"type": "string", "enum": ["long", "short", "pass"]},
        "confidence": {"type": "number", "description": "0..1"},
        "rationale": {"type": "string", "description": "<=2 sentences"},
        "key_risk": {"type": "string", "description": "the main risk to this view"},
    },
    "required": ["side", "confidence", "rationale", "key_risk"],
}

RISK_SCHEMA = {
    "type": "object",
    "properties": {
        "approve": {"type": "boolean"},
        "adjusted_confidence": {"type": "number", "description": "0..1, <= trader confidence"},
        "note": {"type": "string", "description": "<=1 sentence"},
    },
    "required": ["approve", "adjusted_confidence", "note"],
}
