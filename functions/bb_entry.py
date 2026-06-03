"""
BB Entry Scanner
=================
Scans watchlist for BB lower touches.
Auto-adds new signals to positions_bb.csv as Paper trades.

Changes from original:
    - Accepts regime status — skips if PAUSE
    - Auto-adds signals to data/positions_bb.csv as Paper
    - Returns structured result for notify.py

Entry signal : Price <= BB Lower (20, 2)
Trend filter : Price > EMA200 flagged as uptrend (preferred, not hard gate)
"""

import yfinance as yf
import pandas as pd
import time
import os
from datetime import datetime


# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────
BASE_DIR       = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_FILE     = os.path.join(BASE_DIR, "data", "watchlist.csv")
POSITIONS_FILE = os.path.join(BASE_DIR, "data", "positions_bb.csv")
SLEEP_SECONDS  = 0.3

BB_PERIOD      = 20
BB_STD         = 2
EMA_SLOW       = 200
STOP_LOSS_PCT  = 10.0
POSITION_SIZE  = 10000


# ─────────────────────────────────────────────
# HELPER
# ─────────────────────────────────────────────
def nse(symbol):
    return f"{symbol.upper().strip()}.NS"


def load_watchlist(filepath):
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"'{filepath}' not found.")
    df = pd.read_csv(filepath)
    print(f"Loaded {len(df)} stocks from watchlist")
    return df


def load_positions(filepath):
    if not os.path.exists(filepath) or os.path.getsize(filepath) <= 1:
        return pd.DataFrame(columns=['Symbol','EntryDate','EntryPrice','Quantity','TrackType'])
    df = pd.read_csv(filepath)
    df.columns = df.columns.str.strip()
    df['Symbol'] = df['Symbol'].str.strip()
    return df


# ─────────────────────────────────────────────
# INDICATORS
# ─────────────────────────────────────────────
def get_indicators(symbol):
    try:
        ticker = yf.Ticker(nse(symbol))
        df     = ticker.history(period='1y', interval='1d')

        if df.empty or len(df) < EMA_SLOW + 5:
            return None

        close          = df['Close']
        df['BB_Mid']   = close.rolling(BB_PERIOD).mean()
        df['BB_Std']   = close.rolling(BB_PERIOD).std()
        df['BB_Upper'] = df['BB_Mid'] + BB_STD * df['BB_Std']
        df['BB_Lower'] = df['BB_Mid'] - BB_STD * df['BB_Std']
        df['EMA200']   = close.ewm(span=EMA_SLOW, adjust=False).mean()

        latest = df.iloc[-1]
        prev   = df.iloc[-2]

        price    = round(float(latest['Close']), 2)
        bb_upper = round(float(latest['BB_Upper']), 2)
        bb_mid   = round(float(latest['BB_Mid']), 2)
        bb_lower = round(float(latest['BB_Lower']), 2)
        ema200   = round(float(latest['EMA200']), 2)
        change   = round((price - float(prev['Close'])) / float(prev['Close']) * 100, 2)
        stop     = round(price * (1 - STOP_LOSS_PCT / 100), 2)
        above200 = price > ema200

        return {
            'price':    price,
            'change':   change,
            'bb_upper': bb_upper,
            'bb_mid':   bb_mid,
            'bb_lower': bb_lower,
            'ema200':   ema200,
            'above200': above200,
            'stop':     stop,
        }
    except Exception:
        return None


# ─────────────────────────────────────────────
# AUTO ADD TO POSITIONS
# ─────────────────────────────────────────────
def add_position(symbol, ind, positions_df):
    quantity = max(1, int(POSITION_SIZE / ind['price']))
    new_row  = pd.DataFrame([{
        'Symbol':     symbol,
        'EntryDate':  datetime.now().strftime('%Y-%m-%d'),
        'EntryPrice': ind['price'],
        'Quantity':   quantity,
        'TrackType':  'Paper',
    }])
    updated = pd.concat([positions_df, new_row], ignore_index=True)
    updated.to_csv(POSITIONS_FILE, index=False)
    print(f"  Added {symbol} to positions as Paper (qty: {quantity} @ ₹{ind['price']})")
    return updated


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def run(regime='GO'):
    if regime == 'PAUSE':
        print("\nBB Entry Scanner — SKIPPED (market regime: PAUSE)")
        return []

    watchlist     = load_watchlist(INPUT_FILE)
    positions_df  = load_positions(POSITIONS_FILE)
    open_symbols  = set(positions_df['Symbol'].str.strip().tolist())
    total         = len(watchlist)
    results       = []
    added         = []

    print(f"\nBB Entry Scanner — {datetime.now().strftime('%d %b %Y, %I:%M %p')}")
    print(f"  Scanning {total} stocks for BB lower touches...\n")

    start_time = time.time()

    for i, row in watchlist.iterrows():
        symbol     = row['Symbol']
        industry   = row['Industry']
        is_banking = bool(row['IsBanking'])

        elapsed = time.time() - start_time
        rate    = (i + 1) / elapsed if elapsed > 0 else 1
        eta     = int((total - i - 1) / rate)

        print(f"  [{i+1:>2}/{total}] ETA: {eta}s | {symbol:<15}", end='\r')

        ind = get_indicators(symbol)
        if ind is None:
            time.sleep(SLEEP_SECONDS)
            continue

        if ind['price'] <= ind['bb_lower']:
            # Skip if already in open positions
            if symbol in open_symbols:
                print(f"  {symbol}: Already in positions — skipping")
                time.sleep(SLEEP_SECONDS)
                continue

            result = {
                'Symbol':    symbol,
                'Industry':  industry,
                'IsBanking': is_banking,
                'Price':     ind['price'],
                'Change%':   ind['change'],
                'BB Lower':  ind['bb_lower'],
                'BB Mid':    ind['bb_mid'],
                'BB Upper':  ind['bb_upper'],
                'EMA200':    ind['ema200'],
                '>EMA200':   ind['above200'],
                'Stop':      ind['stop'],
            }
            results.append(result)

            # Auto-add to positions as Paper
            positions_df = add_position(symbol, ind, positions_df)
            open_symbols.add(symbol)
            added.append(symbol)

        time.sleep(SLEEP_SECONDS)

    print(f"\n  Done. {len(results)} new signal(s) found and added as Paper.\n")
    return results


if __name__ == "__main__":
    from regime_check import check_regime
    regime_result = check_regime()
    print(f"  Regime: {regime_result['regime']} — {regime_result['message']}")
    signals = run(regime=regime_result['regime'])

    if signals:
        print(f"{'═'*80}")
        print(f"  NEW PAPER ENTRIES ({len(signals)})")
        print(f"  {'SYMBOL':<12} {'PRICE':>8} {'BB LOW':>8} {'EMA200':>8} {'>200':>5}")
        print(f"  {'-'*50}")
        for s in signals:
            trend = '✅' if s['>EMA200'] else '❌'
            print(f"  {s['Symbol']:<12} "
                  f"₹{s['Price']:>8.2f} "
                  f"₹{s['BB Lower']:>8.2f} "
                  f"₹{s['EMA200']:>8.2f} "
                  f"{trend:>5}")
        print(f"{'═'*80}\n")
    else:
        print("  No new entry signals today.")
