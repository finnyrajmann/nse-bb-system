"""
BB Exit Monitor
================
Checks open positions and actions exits automatically.

Changes from original:
    - Auto-logs exits to data/bb_trade_log.csv
    - Auto-removes exited rows from data/positions_bb.csv
    - Returns structured result for notify.py

Exit signal : Price touches or crosses above upper BB
Stop loss   : Price falls 10% below entry price
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
POSITIONS_FILE = os.path.join(BASE_DIR, "data", "positions_bb.csv")
TRADE_LOG      = os.path.join(BASE_DIR, "data", "bb_trade_log.csv")
SLEEP_SECONDS  = 0.3

BB_PERIOD      = 20
BB_STD         = 2
STOP_LOSS_PCT  = 10.0


# ─────────────────────────────────────────────
# HELPER
# ─────────────────────────────────────────────
def nse(symbol):
    return f"{symbol.upper().strip()}.NS"


def load_positions(filepath):
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"'{filepath}' not found.")
    df = pd.read_csv(filepath)
    df.columns = df.columns.str.strip()
    df['Symbol']     = df['Symbol'].str.strip()
    df['EntryPrice'] = df['EntryPrice'].astype(float)
    df['Quantity']   = df['Quantity'].astype(int)
    if 'TrackType' not in df.columns:
        df['TrackType'] = 'Real'
    df['TrackType'] = df['TrackType'].str.strip()
    return df


# ─────────────────────────────────────────────
# INDICATORS
# ─────────────────────────────────────────────
def get_indicators(symbol):
    try:
        ticker = yf.Ticker(nse(symbol))
        df     = ticker.history(period='3mo', interval='1d')

        if df.empty or len(df) < BB_PERIOD + 2:
            return None

        close          = df['Close']
        df['BB_Mid']   = close.rolling(BB_PERIOD).mean()
        df['BB_Std']   = close.rolling(BB_PERIOD).std()
        df['BB_Upper'] = df['BB_Mid'] + BB_STD * df['BB_Std']
        df['BB_Lower'] = df['BB_Mid'] - BB_STD * df['BB_Std']

        latest = df.iloc[-1]
        prev   = df.iloc[-2]

        price    = round(float(latest['Close']), 2)
        bb_upper = round(float(latest['BB_Upper']), 2)
        bb_mid   = round(float(latest['BB_Mid']), 2)
        bb_lower = round(float(latest['BB_Lower']), 2)
        change   = round((price - float(prev['Close'])) / float(prev['Close']) * 100, 2)

        return {
            'price':    price,
            'change':   change,
            'bb_upper': bb_upper,
            'bb_mid':   bb_mid,
            'bb_lower': bb_lower,
        }
    except Exception:
        return None


# ─────────────────────────────────────────────
# AUTO LOG EXIT TO TRADE LOG
# ─────────────────────────────────────────────
def log_exit(pos, ind, exit_type, exit_reason, days_held):
    pnl       = round((ind['price'] - pos['EntryPrice']) * pos['Quantity'], 2)
    pnl_pct   = round((ind['price'] - pos['EntryPrice']) / pos['EntryPrice'] * 100, 2)
    capital   = round(pos['EntryPrice'] * pos['Quantity'], 2)

    row = {
        'Symbol':     pos['Symbol'],
        'EntryDate':  pos['EntryDate'],
        'EntryPrice': pos['EntryPrice'],
        'Quantity':   pos['Quantity'],
        'Capital':    capital,
        'ExitDate':   datetime.now().strftime('%Y-%m-%d'),
        'ExitPrice':  ind['price'],
        'PnL':        pnl,
        'PnL%':       pnl_pct,
        'DaysHeld':   days_held,
        'ExitReason': exit_reason,
        'TrackType':  pos['TrackType'],
    }

    log_df  = pd.DataFrame([row])
    columns = ['Symbol','EntryDate','EntryPrice','Quantity','Capital',
               'ExitDate','ExitPrice','PnL','PnL%','DaysHeld','ExitReason','TrackType']

    if os.path.exists(TRADE_LOG) and os.path.getsize(TRADE_LOG) > 1:
        existing = pd.read_csv(TRADE_LOG)
        # Remove # comments if any
        existing = existing[~existing['Symbol'].astype(str).str.startswith('#')]
        updated  = pd.concat([existing, log_df[columns]], ignore_index=True)
    else:
        updated  = log_df[columns]

    updated.to_csv(TRADE_LOG, index=False)
    print(f"  Logged exit for {pos['Symbol']} to {TRADE_LOG}")


# ─────────────────────────────────────────────
# AUTO REMOVE FROM POSITIONS
# ─────────────────────────────────────────────
def remove_position(positions_df, symbol):
    updated = positions_df[positions_df['Symbol'] != symbol].copy()
    updated.to_csv(POSITIONS_FILE, index=False)
    print(f"  Removed {symbol} from {POSITIONS_FILE}")
    return updated


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def run():
    positions = load_positions(POSITIONS_FILE)
    total     = len(positions)
    results   = []
    exited    = []

    print(f"\nBB Exit Monitor — {datetime.now().strftime('%d %b %Y, %I:%M %p')}")
    print(f"  Checking {total} positions...\n")

    for _, pos in positions.iterrows():
        symbol      = pos['Symbol']
        entry_price = pos['EntryPrice']
        quantity    = pos['Quantity']
        entry_date  = pd.to_datetime(pos['EntryDate'])
        days_held   = (datetime.now() - entry_date).days
        track_type  = pos['TrackType']
        stop_price  = round(entry_price * (1 - STOP_LOSS_PCT / 100), 2)

        print(f"  Checking {symbol}...", end='\r')
        ind = get_indicators(symbol)

        if ind is None:
            print(f"  {symbol}: Could not fetch data — skipping")
            continue

        pnl     = round((ind['price'] - entry_price) * quantity, 2)
        pnl_pct = round((ind['price'] - entry_price) / entry_price * 100, 2)

        exit_type   = None
        exit_reason = None

        if ind['price'] >= ind['bb_upper']:
            exit_type   = 'PROFIT'
            exit_reason = f"Price at BB Upper (₹{ind['bb_upper']:.2f})"
        elif ind['price'] <= stop_price:
            exit_type   = 'STOP'
            exit_reason = f"Stop loss hit (₹{stop_price:.2f})"

        result = {
            'Symbol':     symbol,
            'TrackType':  track_type,
            'EntryPrice': entry_price,
            'EntryDate':  pos['EntryDate'],
            'Quantity':   quantity,
            'Price':      ind['price'],
            'Change%':    ind['change'],
            'PnL':        pnl,
            'PnL%':       pnl_pct,
            'BBLower':    ind['bb_lower'],
            'BBMid':      ind['bb_mid'],
            'BBUpper':    ind['bb_upper'],
            'Stop':       stop_price,
            'DaysHeld':   days_held,
            'ExitType':   exit_type,
            'ExitReason': exit_reason,
        }
        results.append(result)

        # Auto-action exits
        if exit_type is not None:
            log_exit(pos, ind, exit_type, exit_reason, days_held)
            positions = remove_position(positions, symbol)
            exited.append(result)

        time.sleep(SLEEP_SECONDS)

    print(f"\n  Done. {len(exited)} exit(s) actioned, {len(results)-len(exited)} holding.\n")
    return results


if __name__ == "__main__":
    results = run()

    exits = [r for r in results if r['ExitType'] is not None]
    holds = [r for r in results if r['ExitType'] is None]

    print(f"{'═'*90}")
    if exits:
        print(f"  EXITED ({len(exits)}):")
        for r in exits:
            print(f"  {'🟢' if r['PnL']>=0 else '🔴'} {r['Symbol']:<12} "
                  f"{r['PnL%']:+.2f}%  ₹{r['PnL']:+.0f}  — {r['ExitReason']}")

    if holds:
        print(f"\n  HOLDING ({len(holds)}):")
        print(f"  {'SYMBOL':<12} {'ENTRY':>8} {'PRICE':>8} {'P&L%':>7} {'P&L₹':>9} {'DAYS':>5}")
        print(f"  {'-'*55}")
        for r in holds:
            print(f"  {r['Symbol']:<12} "
                  f"₹{r['EntryPrice']:>8.2f} "
                  f"₹{r['Price']:>8.2f} "
                  f"{r['PnL%']:>+7.2f}% "
                  f"₹{r['PnL']:>+9.0f} "
                  f"{r['DaysHeld']:>5}d")

    total_pnl = sum(r['PnL'] for r in results)
    print(f"\n  Total Portfolio P&L : ₹{total_pnl:+.0f}")
    print(f"{'═'*90}\n")
