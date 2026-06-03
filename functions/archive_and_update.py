"""
Archive and Update Positions
==============================
Run this after entry scanners each morning.
- Adds all new signals to positions.csv and positions_bb.csv as Paper trades
- Archives buy_today.csv and bb_buy_today.csv with today's date
- Skips symbols already in positions file
"""

import pandas as pd
import os
import shutil
from datetime import datetime

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────
BUY_FILE        = "buy_today.csv"
BB_BUY_FILE     = "bb_buy_today.csv"
POSITIONS_FILE  = "positions.csv"
BB_POSITIONS    = "positions_bb.csv"
ARCHIVE_DIR     = "archive"
TODAY           = datetime.now().strftime("%Y-%m-%d")


# ─────────────────────────────────────────────
# HELPER
# ─────────────────────────────────────────────
def load_positions(filepath):
    df = pd.read_csv(filepath)
    df.columns = df.columns.str.strip()
    return df


def get_existing_symbols(filepath):
    df = load_positions(filepath)
    if df.empty or 'Symbol' not in df.columns:
        return set()
    return set(df['Symbol'].str.strip().tolist())


def is_file_usable(filepath):
    """Returns True only if file exists and has content.
    Handles both missing files and 0-byte files gracefully."""
    if not os.path.exists(filepath):
        print(f"\n{filepath} not found — skipping")
        return False
    if os.path.getsize(filepath) == 0:
        print(f"\n{filepath} is empty (0 bytes) — no signals today")
        archive_file(filepath)
        return False
    return True


def append_to_positions(positions_file, new_rows):
    """Append new rows to positions file, skip existing symbols."""
    existing = get_existing_symbols(positions_file)
    added    = 0
    skipped  = 0

    with open(positions_file, 'a') as f:
        for row in new_rows:
            if row['Symbol'] in existing:
                print(f"  Skipping {row['Symbol']} — already in positions")
                skipped += 1
                continue
            f.write(
                f"{row['Symbol']},{TODAY},"
                f"{row['EntryPrice']},{row['Quantity']},Paper\n"
            )
            print(f"  Added {row['Symbol']} @ ₹{row['EntryPrice']}")
            added += 1

    return added, skipped


def archive_file(filepath):
    """Copy file to archive with date in filename."""
    if not os.path.exists(filepath):
        print(f"  {filepath} not found — skipping archive")
        return
    basename  = os.path.splitext(os.path.basename(filepath))[0]
    dest      = os.path.join(ARCHIVE_DIR, f"{basename}_{TODAY}.csv")
    shutil.copy(filepath, dest)
    print(f"  Archived → {dest}")


def calculate_quantity(price, capital_per_trade=10000):
    from math import floor
    qty = floor(capital_per_trade / price)
    return max(qty, 1)


# ─────────────────────────────────────────────
# PROCESS RSI/EMA SCANNER OUTPUT
# ─────────────────────────────────────────────
def process_buy_today():
    if not os.path.exists(BUY_FILE) or os.path.getsize(BUY_FILE) <= 1:
        print("  No buy file today — skipping position update.")
        return

    df = pd.read_csv(BUY_FILE)
    if df.empty:
        print(f"\n{BUY_FILE} is empty — no signals today")
        archive_file(BUY_FILE)
        return

    print(f"\nProcessing {BUY_FILE} — {len(df)} signals")

    new_rows = []
    for _, row in df.iterrows():
        new_rows.append({
            'Symbol':     row['Symbol'].strip(),
            'EntryPrice': row['Price'],
            'Quantity':   calculate_quantity(row['Price']),
        })

    added, skipped = append_to_positions(POSITIONS_FILE, new_rows)
    print(f"  Added: {added} | Skipped (duplicate): {skipped}")
    archive_file(BUY_FILE)


# ─────────────────────────────────────────────
# PROCESS BB SCANNER OUTPUT
# ─────────────────────────────────────────────
def process_bb_buy_today():
    if not os.path.exists(BUY_FILE) or os.path.getsize(BUY_FILE) <= 1:
        print("  No buy file today — skipping position update.")
        return

    df = pd.read_csv(BB_BUY_FILE)
    if df.empty:
        print(f"\n{BB_BUY_FILE} is empty — no signals today")
        archive_file(BB_BUY_FILE)
        return

    print(f"\nProcessing {BB_BUY_FILE} — {len(df)} signals")

    new_rows = []
    for _, row in df.iterrows():
        new_rows.append({
            'Symbol':     row['Symbol'].strip(),
            'EntryPrice': row['Price'],
            'Quantity':   calculate_quantity(row['Price']),
        })

    added, skipped = append_to_positions(BB_POSITIONS, new_rows)
    print(f"  Added: {added} | Skipped (duplicate): {skipped}")
    archive_file(BB_BUY_FILE)


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
if __name__ == '__main__':
    # Create archive directory
    os.makedirs(ARCHIVE_DIR, exist_ok=True)

    print(f"Archive and Update Positions — {TODAY}")
    print(f"{'═'*50}")

    process_buy_today()
    process_bb_buy_today()

    print(f"\n{'═'*50}")
    print(f"Done. Check positions.csv and positions_bb.csv")

    # Show current position counts
    pos    = load_positions(POSITIONS_FILE)
    bb_pos = load_positions(BB_POSITIONS)
    print(f"\nCurrent positions:")
    print(f"  RSI/EMA strategy : {len(pos)} positions")
    print(f"  BB strategy      : {len(bb_pos)} positions")
