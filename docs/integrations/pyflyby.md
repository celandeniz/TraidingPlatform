# pyflyby (D.E. Shaw) — research-notebook auto-import

**What it is:** [pyflyby](https://github.com/deshaw/pyflyby) auto-imports symbols in
IPython/Jupyter and tidies imports in `.py` files. It's a **developer convenience for
research notebooks only** — it touches none of the trading engine, brokers, or runner.

**Install (dev-only, optional):**

```bash
pip install pyflyby
```

**Use it in research:**

- Enable autoimport in an IPython/Jupyter session so `pd`, `np`, etc. import on first use:

  ```python
  %load_ext pyflyby
  # now: df = pd.DataFrame(...)  # pandas auto-imported, no explicit `import pandas as pd`
  ```

- Tidy imports in a script from the shell:

  ```bash
  tidy-imports backend/backtest/run_scalp.py   # add missing / remove unused imports
  py backend/backtest/run.py                    # run with autoimport
  ```

**Scope / honesty:** purely ergonomic for ad-hoc research. It is intentionally **not** a
runtime dependency of the platform and is listed (commented) under the optional block in
`requirements.txt`. Do not rely on autoimport inside committed modules — keep explicit
imports there.
