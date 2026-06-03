"""
Calculate PnL for trade_log.csv
- Fills in PnL and PnL% where values are missing or '-'
- Auto-computes Capital (EntryPrice * Quantity) where '-' or missing
"""
import pandas as pd

TRADES_FILE = "trade_log.csv"

df = pd.read_csv(TRADES_FILE, dtype=str)  # read everything as string first

def to_float(val):
    """Return float or None if value is missing/dash."""
    try:
        v = str(val).strip()
        if v in ('-', '', 'nan', 'None'):
            return None
        return float(v)
    except:
        return None

updated = 0
for idx, row in df.iterrows():
    entry = to_float(row['EntryPrice'])
    exit_ = to_float(row['ExitPrice'])
    qty   = to_float(row['Quantity'])

    # Auto-compute Capital if missing
    if entry is not None and qty is not None:
        cap = to_float(row.get('Capital'))
        if cap is None:
            df.at[idx, 'Capital'] = str(round(entry * qty, 2))

    # Compute PnL and PnL% only if all three values are present
    if entry is not None and exit_ is not None and qty is not None:
        pnl     = round((exit_ - entry) * qty, 2)
        pnl_pct = round((exit_ - entry) / entry * 100, 2)
        df.at[idx, 'PnL']  = str(pnl)
        df.at[idx, 'PnL%'] = str(pnl_pct)
        updated += 1

df.to_csv(TRADES_FILE, index=False)

print(f"Updated trade_log.csv ({updated} rows computed):")
print(df[['Symbol','EntryPrice','ExitPrice','Quantity','Capital','PnL','PnL%','DaysHeld']].to_string(index=False))

# Summary of closed trades (those with PnL computed)
closed = df[df['PnL'].apply(lambda x: to_float(x) is not None)].copy()
if not closed.empty:
    closed['PnL_num'] = closed['PnL'].apply(to_float)
    total_pnl = closed['PnL_num'].sum()
    winners   = (closed['PnL_num'] > 0).sum()
    losers    = (closed['PnL_num'] < 0).sum()
    print(f"\n── Summary ──────────────────────────")
    print(f"  Closed trades : {len(closed)}")
    print(f"  Winners       : {winners}")
    print(f"  Losers        : {losers}")
    print(f"  Total P&L     : ₹{total_pnl:+.2f}")
