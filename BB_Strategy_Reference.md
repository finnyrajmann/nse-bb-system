# BB Strategy — Quick Reference

> One page. Everything you need to run this system without digging into code.

---

## What This System Does

Buys stocks when they touch the lower Bollinger Band (oversold / mean-reversion setup),
and sells when they touch the upper Bollinger Band or hit a hard stop loss.
It is a **swing trading system** — typical hold is 1 to 10 weeks.

---

## The Two Commands (Daily Run)

```bash
cd ~/Documents/student/nifty250_work
source myenv/bin/activate

python3 bb_exit.py      # Step 1 — check open positions first
python3 bb_entry.py     # Step 2 — scan for new entries
```

Run after market opens (9:30 AM IST is fine). Takes ~2 minutes.

---

## Entry Rule (`bb_entry.py`)

| Parameter     | Value                        |
|---------------|------------------------------|
| BB Period     | 20 days                      |
| BB Std Dev    | 2                            |
| Signal        | Price ≤ BB Lower             |
| Trend filter  | Price > EMA 200 (flagged ✅) |
| Stop loss     | 10% below entry price        |
| Universe      | `watchlist.csv` (17 stocks)  |

**What to do when signals appear:**
- Prefer stocks marked ✅ (above EMA200 = uptrend intact)
- Avoid ❌ stocks unless you have a strong chart reason
- Position size: ~₹10,000 per stock
- Log the entry manually in `positions_bb.csv`

**`positions_bb.csv` format:**
```
Symbol,EntryDate,EntryPrice,Quantity,TrackType
NMDC,2026-03-23,75.00,133,Paper
```
`TrackType` = `Real` or `Paper`

---

## Exit Rule (`bb_exit.py`)

| Condition             | Action          |
|-----------------------|-----------------|
| Price ≥ BB Upper      | EXIT — Profit   |
| Price ≤ Entry × 0.90  | EXIT — Stop loss|
| Otherwise             | HOLD            |

**What to do when exit signals appear:**
- Log the exit in `bb_trade_log.csv`
- Remove the row from `positions_bb.csv`

**`bb_trade_log.csv` format:**
```
Symbol,EntryDate,EntryPrice,Quantity,Capital,ExitDate,ExitPrice,PnL,PnL%,DaysHeld,ExitReason,TrackType
```

---

## Indicators — How They Work

**Bollinger Bands (20, 2)**
- BB Mid = 20-day simple moving average of close price
- BB Upper = BB Mid + (2 × 20-day std deviation)
- BB Lower = BB Mid − (2 × 20-day std deviation)
- Price touching lower band = statistically oversold → potential bounce
- Price touching upper band = statistically overbought → take profit

**EMA 200**
- 200-day exponential moving average
- Price above EMA200 = stock is in a long-term uptrend
- Used as a filter only — not an exit signal

**Stop Loss**
- Fixed at 10% below entry price
- Calculated at entry, does not trail

---

## Files — What Each One Does

| File                | Purpose                              | Touch frequency     |
|---------------------|--------------------------------------|---------------------|
| `bb_entry.py`       | Scans watchlist for entry signals    | Read-only, runs daily |
| `bb_exit.py`        | Checks open positions for exits      | Read-only, runs daily |
| `watchlist.csv`     | 17-stock universe with industry tags | Edit only to add/remove stocks |
| `positions_bb.csv`  | Currently open positions             | **Edit manually** after entry/exit |
| `bb_trade_log.csv`  | Completed trade history              | **Edit manually** after exit |
| `bb_buy_today.csv`  | Today's entry signals (auto-generated) | Auto — don't edit |
| `bb_buy_today.txt`  | Symbol list of today's signals       | Auto — don't edit |

**Everything else in the folder can be ignored.**

---

## Track Record (as of Jun 2026)

| Metric            | Value              |
|-------------------|--------------------|
| Trades tracked    | 7                  |
| Win rate          | 7/7 (100%)         |
| Avg return        | +7.32% per trade   |
| Avg hold time     | ~51 days           |
| Best trade        | NMDC +28.85%       |
| Total P&L         | ₹+4,953 (paper)    |

*Note: Small sample size. Win rate will normalise over more trades.
Expectancy is positive — the system has structural merit.*

---

## Open Positions (as of Jun 2026)

| Symbol      | Entry ₹ | Current ₹ | P&L%   | Days | Status         |
|-------------|---------|-----------|--------|------|----------------|
| NMDC        | 75.00   | 96.64     | +28.85% | 71  | ⚠ EXIT SIGNAL |
| PFC         | 387.00  | 410.50    | +6.07%  | 71  | Hold           |
| DRREDDY     | 1253.30 | 1274.20   | +1.67%  | 70  | Hold           |
| TORNTPOWER  | 1362.80 | 1412.60   | +3.65%  | 70  | Hold           |
| NTPC        | 358.80  | 364.25    | +1.52%  | 57  | Hold           |

---

## Known Gaps (for when you have mind space)

1. **No formal backtest yet** — 3-year historical backtest on the 17 stocks would
   give statistical confidence to deploy real capital. Logic is already in `bb_entry.py`
   and `bb_exit.py` — just needs a historical simulation wrapper.

2. **No regime filter** — system doesn't know if the broader market is in a downtrend.
   During the March 2026 selloff, the EMA system got hurt badly. BB held better
   but a Nifty direction check (e.g. Nifty > its own EMA50) before firing entries
   would add another layer of protection.

3. **bb_trade_log.csv needs cleanup** — the two completed trades (LUPIN, BSE) are
   commented out with `#`. Remove the `#` to make them proper records.

---

*Last updated: June 2026*
