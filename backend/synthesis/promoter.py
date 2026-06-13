"""Persist + register a promoted strategy for the PAPER runner.

Structural paper-only guarantee: this module writes files and a manifest and
loads classes. It imports NO executor, NO brokers, and NOTHING from
backend/execution/* — so a generated strategy cannot reach a live broker from
here. Order flow still goes through the runner -> OMS -> guards -> executor path,
where the live-trading hard-block lives, unchanged.

Persistence mirrors the tournament store. The manifest is the source of truth for
which generated strategies the runner may load (only pre-validated files).
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from ..settings import REPO_DIR

GEN_DIR = REPO_DIR / "backend" / "store" / "generated_strategies"
MANIFEST = GEN_DIR / "manifest.json"


def _slug(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", text.strip().lower()).strip("_")
    return s or "strategy"


def _json_safe(o):
    """Coerce numpy scalars (and friends) so json.dumps never fails on metrics."""
    try:
        return float(o)
    except (TypeError, ValueError):
        return str(o)


def _store_path(dest: Path) -> str:
    """Repo-relative path when under the repo (portable), else absolute."""
    try:
        return str(dest.relative_to(REPO_DIR))
    except ValueError:
        return str(dest)


def _resolve(file: str):
    """Resolve a manifest path and require it to live under GEN_DIR. Returns the
    Path, or None if it escapes the store (tampered manifest / path traversal)."""
    p = Path(file)
    p = (p if p.is_absolute() else (REPO_DIR / p)).resolve()
    try:
        p.relative_to(GEN_DIR.resolve())
    except ValueError:
        return None
    return p


def _load_manifest() -> dict:
    if MANIFEST.exists():
        try:
            return json.loads(MANIFEST.read_text())
        except ValueError:
            return {}
    return {}


def promote(name: str, source: str, class_name: str, metrics: dict, *,
            brief_text: str = "") -> dict:
    """Write the source + register it in the manifest (paper-only). Returns a
    summary dict; never raises into the pipeline."""
    try:
        key = _slug(name)
        version = time.strftime("%Y%m%d%H%M%S")
        dest_dir = GEN_DIR / key
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{version}.py"
        dest.write_text(source, encoding="utf-8")

        manifest = _load_manifest()
        manifest[key] = {
            "class_name": class_name,
            "file": _store_path(dest),
            "version": version,
            "metrics": metrics,
            "brief": brief_text,
            "paper_only": True,
            "promoted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST.write_text(json.dumps(manifest, indent=1, default=_json_safe))
        return {"ok": True, "key": key, "file": manifest[key]["file"]}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": str(exc)}


def load_promoted() -> dict:
    """name -> strategy class, for every entry in the manifest. Bad/missing files
    are skipped (best-effort), so a corrupt entry never breaks the runner."""
    from .harness import load_strategy_class
    from .validator import validate_source

    out: dict = {}
    manifest = _load_manifest()
    for key, entry in manifest.items():
        try:
            path = _resolve(entry["file"])
            if path is None:  # escapes GEN_DIR — refuse
                continue
            source = path.read_text(encoding="utf-8")
            ok, _, class_name = validate_source(source)  # re-validate on load
            if not ok:
                continue
            out[key] = load_strategy_class(source, class_name or entry["class_name"])
        except Exception:  # noqa: BLE001 - skip a bad entry, keep the rest
            continue
    return out
