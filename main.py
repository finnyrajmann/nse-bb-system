"""
NSE BB Swing Trader — Main Orchestrator
=========================================
Runs the full daily pipeline in sequence:

    1. Regime Check    — Nifty EMA50 gate
    2. BB Exit Monitor — auto-log exits, auto-remove from positions
    3. BB Entry Scanner — auto-add new signals as Paper (only if GO)
    4. GitHub Sync     — commit updated data files back to repo
    5. Notify          — send Gmail summary

Run daily at 9:30 AM IST via cron or DigitalOcean Functions.
"""

import sys
import os

# Make functions/ importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'functions'))

from regime_check import check_regime
from bb_exit      import run as run_exit
from bb_entry     import run as run_entry
from github_sync  import sync as github_sync
from notify       import run as run_notify


def main():
    print("\n" + "═"*60)
    print("  NSE BB SWING TRADER — Daily Run")
    print("═"*60)

    # ── Step 1: Regime Check ──
    print("\n[1/5] Regime Check...")
    regime_result = check_regime()
    print(f"      {regime_result['message']}")

    # ── Step 2: BB Exit Monitor ──
    print("\n[2/5] BB Exit Monitor...")
    exit_results = run_exit()
    exits  = [r for r in exit_results if r['ExitType'] is not None]
    holds  = [r for r in exit_results if r['ExitType'] is None]
    print(f"      {len(exits)} exit(s) actioned | {len(holds)} holding")

    # ── Step 3: BB Entry Scanner ──
    print("\n[3/5] BB Entry Scanner...")
    entry_results = run_entry(regime=regime_result['regime'])
    print(f"      {len(entry_results)} new signal(s) added as Paper")

    # ── Step 4: GitHub Sync ──
    print("\n[4/5] GitHub Sync...")
    github_sync()

    # ── Step 5: Notify ──
    print("\n[5/5] Sending Gmail summary...")
    run_notify(regime_result, exits, entry_results, holds)

    print("\n" + "═"*60)
    print("  Done.")
    print("═"*60 + "\n")


if __name__ == "__main__":
    main()
