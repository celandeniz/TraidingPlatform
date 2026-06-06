"""Refresh the bundled index-constituent snapshots in backend/universe_data/.

Run manually (needs network + lxml for the NASDAQ-100 Wikipedia table):
    .venv/bin/python -m backend.scripts.refresh_universe

S&P 500: datahub constituents CSV. NASDAQ-100: Wikipedia (requires lxml). Writes
sp500.json, nasdaq100.json, universe_meta.json. The runtime never calls this — it
only reads the committed snapshots — so production has no network dependency.
"""
from __future__ import annotations

import csv
import io
import json
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "universe_data"
_UA = {"User-Agent": "Mozilla/5.0 (universe refresh)"}


def _get(url: str, timeout: int = 25) -> str:
    req = urllib.request.Request(url, headers=_UA)
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace")


def fetch_sp500() -> list[str]:
    txt = _get("https://raw.githubusercontent.com/datasets/"
               "s-and-p-500-companies/main/data/constituents.csv")
    out = {(r.get("Symbol") or "").strip().replace(".", "-")
           for r in csv.DictReader(io.StringIO(txt)) if r.get("Symbol")}
    return sorted(s for s in out if s)


def fetch_nasdaq100() -> list[str]:
    import pandas as pd  # needs lxml installed

    html = _get("https://en.wikipedia.org/wiki/Nasdaq-100")
    for t in pd.read_html(io.StringIO(html)):
        cols = [str(c).lower() for c in t.columns]
        key = next((c for c in ("ticker", "symbol") if c in cols), None)
        if not key:
            continue
        col = t.columns[cols.index(key)]
        cand = [str(s).strip().upper().replace(".", "-") for s in t[col].tolist()
                if str(s).strip()]
        cand = [c for c in cand if 1 <= len(c) <= 6 and c.replace("-", "").isalnum()]
        if 80 <= len(cand) <= 110:
            return sorted(set(cand))
    raise RuntimeError("could not locate the NASDAQ-100 components table")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    sp = fetch_sp500()
    json.dump(sp, open(OUT / "sp500.json", "w"), indent=0)
    ndx = fetch_nasdaq100()
    json.dump(ndx, open(OUT / "nasdaq100.json", "w"), indent=0)
    combined = sorted(set(sp) | set(ndx))
    json.dump({"source": {"sp500": "datahub/s-and-p-500-companies",
                          "nasdaq100": "wikipedia/Nasdaq-100"},
               "counts": {"sp500": len(sp), "nasdaq100": len(ndx),
                          "combined": len(combined)}},
              open(OUT / "universe_meta.json", "w"), indent=2)
    print(f"sp500={len(sp)} nasdaq100={len(ndx)} combined={len(combined)}")


if __name__ == "__main__":
    main()
