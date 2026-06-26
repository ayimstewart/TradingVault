#!/bin/bash
# start.sh — Run this once when you open Cursor
# Or add to Cursor's terminal startup: bash start.sh

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║         TRADING VAULT — AUTO START               ║"
echo "║         $(date '+%Y-%m-%d %H:%M UTC')                    ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# 1. Pull latest from GitHub
echo "[1/4] Pulling latest from GitHub..."
git pull --quiet && echo "      ✓ Up to date" || echo "      ⚠ Git pull failed"

# 2. Update submodules (get latest from reference repos)
echo "[2/4] Updating reference repos..."
git submodule update --remote --quiet 2>/dev/null && \
  echo "      ✓ AI-Trader, Kronos, notebooklm-py, llmwiki updated" || \
  echo "      ⚠ Submodule update failed (offline?)"

# 3. Run the full pipeline (all steps: research → checklist → orders → publish)
echo "[3/4] Running full pipeline..."
cd agent && python3 full_pipeline.py
cd ..

# 4. Show build queue status
echo ""
echo "[4/4] Build queue status:"
echo "      Completed:"
grep "\- \[x\]" .cursorrules | sed 's/- \[x\]/      ✓/' 
echo ""
echo "      Next to build:"
grep "\- \[ \]" .cursorrules | head -3 | sed 's/- \[ \]/      →/'
echo ""
echo "══════════════════════════════════════════════════"
echo "  Claude Code is ready. Tell it:"
echo "  'Read CLAUDE.md and continue building'"
echo "══════════════════════════════════════════════════"
echo ""
