# SETUP.md — Getting Everything Running (Mac)

---

## Step 0 — Check what you have

Open Terminal and run:
```zsh
python3 --version
pip3 --version
brew --version
```

If any say "command not found", follow the relevant step below.

---

## Step 1 — Install Homebrew (if missing)

```zsh
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

---

## Step 2 — Install Python (if missing)

```zsh
brew install python
```

Then verify:
```zsh
python3 --version   # should say 3.10 or higher
pip3 --version      # should respond
```

---

## Step 3 — Install Cursor

Download from **cursor.com**, install, open it.
`Settings > Models` → select **claude-sonnet-4-6**

---

## Step 4 — Open the Vault in Cursor

```
File > Open Folder → select your TradingVault folder
```

---

## Step 5 — Install the agent dependencies

From inside the TradingVault folder in Terminal:

```zsh
cd agent
pip3 install -r requirements.txt
```

---

## Step 6 — Run your first session

```zsh
# You must be inside TradingVault/agent/
python3 run_session.py
```

---

## Step 7 — Install notebooklm-py

```zsh
# Install uv first (recommended):
curl -LsSf https://astral.sh/uv/install.sh | sh

# Then restart Terminal, and install notebooklm-py:
uv tool install "notebooklm-py[browser,mcp]"

# Authenticate:
notebooklm login

# Verify:
notebooklm auth check --test --json

# Connect to Cursor (one command, writes config automatically):
notebooklm mcp install cursor
```

Restart Cursor after this. NotebookLM is now a native MCP tool inside Claude Code.

---

## Step 8 — Import your vault sources into NotebookLM

```zsh
# From TradingVault/ directory:
notebooklm use "Master Brain"
notebooklm source add sources/*.md
notebooklm source wait
```

---

## Daily Workflow

```zsh
# 1. Open Terminal, navigate to vault:
cd ~/wherever/TradingVault/agent

# 2. Run the session:
python3 run_session.py

# 3. Import today's brief:
notebooklm source add ../sources/$(date +%Y-%m-%d)-morning-brief.md
notebooklm source wait

# 4. Query your brain:
notebooklm ask "Which assets have the cleanest setup today?"
```

---

## Quick Reference — Mac commands

| What you want | Mac command |
|---------------|-------------|
| Run Python    | `python3`   |
| Install packages | `pip3 install` |
| Check Python version | `python3 --version` |
| Navigate into agent/ | `cd agent` (from TradingVault/) |
| Go up one folder | `cd ..` |
| See where you are | `pwd` |

---

## File Reference

```
TradingVault/
├── CLAUDE.md              ← Agent directive
├── SETUP.md               ← This file
├── rules/
│   └── rules.md           ← Cockpit Checklist
├── logs/
│   ├── decisions-log.md   ← Signal log
│   └── session-notes.md   ← Morning Briefs
├── sources/               ← Research → NotebookLM
└── agent/
    ├── requirements.txt   ← pip3 install -r requirements.txt
    ├── data_fetcher.py    ← Pulls OHLCV, calculates EMAs + ATR
    ├── signal_checker.py  ← Cockpit Checklist enforcement
    └── run_session.py     ← python3 run_session.py ← START HERE
```
