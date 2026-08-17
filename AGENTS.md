# AGENTS.md

## Cursor Cloud specific instructions

### What this repo is
A deterministic **crypto trading-analysis agent** implemented as a set of Python CLI scripts in `agent/`. There is **no web server, GUI, or long-running service** — every entry point is a script you run from the terminal and its output is printed plus (for most flows) written as a markdown report into `sources/`. Behavior/rules context lives in `CLAUDE.md`, `.cursorrules`, and `rules/`.

### Dependencies
- Declared deps are in `agent/requirements.txt` (`ccxt`, `pandas`). The startup update script installs these.
- `numpy` and `requests` are imported at module top-level by extended modules (`pattern_db.py`, `kronos_probability.py`, `ai_trader_publisher.py`, `ai_trader_bridge.py`, `quant_mind_fetcher.py`) but are **not** listed in `requirements.txt`; the update script installs them explicitly so those modules import cleanly.
- Heavy/optional integrations are **lazy-imported inside functions and degrade gracefully** if missing: `torch`/`transformers`/Kronos `model` (kronos_probability), `turbovec` (pattern_db), `async_rithmic`/`rithmic` (rithmic_executor), and the `notebooklm` CLI (notebooklm_bridge). They are not needed for the core analysis flow, so do not install them unless a task specifically requires that integration.

### Running the app
- **Always run scripts from inside the `agent/` directory** — modules use `sys.path.insert` + sibling imports (e.g. `from data_fetcher import ...`) that assume `agent/` is the working directory.
- Cleanest end-to-end core flow (fetch live data → classify → write Morning Brief): `cd agent && python3 data_fetcher.py` → writes `sources/YYYY-MM-DD-morning-brief.md`.
- Signal/backtest engine on historical data: `cd agent && python3 backtester.py` → writes `sources/YYYY-MM-DD-backtest-1w.md`.
- Master orchestrator: `cd agent && python3 full_pipeline.py` (optional `--account 10000`); optional pipeline steps that need un-installed integrations are skipped with warnings.

### Network requirement
Core flows fetch **live public market data from Kraken** (`api.kraken.com`) via `ccxt` — no API key needed, but outbound network egress is required. If data fetches error, suspect egress/network before code.

### Known pre-existing bug (not an environment issue)
`agent/run_session.py` (the "START HERE" script) currently crashes at Step 4c with `NameError: name 'weekly_data' is not defined` (a variable-scope defect in `step_4c_find_entries`). Steps 1–4b (rules load, live fetch, Cockpit Checklist, harmonic scan) run fine before the crash. Use `data_fetcher.py` for a clean Morning Brief demonstration until that bug is fixed.

### Tests / lint
There is no test suite and no lint config in this repo. Use `python3 -m py_compile agent/*.py` as a quick sanity check that modules parse/compile.
