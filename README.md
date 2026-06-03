# NSE BB Swing Trader

Automated Bollinger Band swing trading system for NSE stocks.
Runs daily via DigitalOcean Functions and sends a Gmail summary.

## How It Works

1. **Regime Check** — Nifty50 must be above its EMA50 before any entries are considered
2. **BB Exit Monitor** — checks open positions, auto-logs exits, auto-removes from positions file
3. **BB Entry Scanner** — scans 17-stock watchlist for BB lower touches, auto-adds as Paper trade
4. **Gmail Notification** — sends daily summary with exits, new entries, and open positions P&L

## Strategy Rules

| | Rule |
|---|---|
| Entry | Price ≤ BB Lower (20, 2) |
| Trend filter | Price > EMA200 preferred |
| Exit (profit) | Price ≥ BB Upper |
| Exit (stop) | Price 10% below entry |
| Position size | ~₹10,000 per stock |

## Repo Structure
nse-bb-system/
├── functions/
│   ├── regime_check.py     # Nifty EMA50 gate
│   ├── bb_exit.py          # Exit monitor + auto-update
│   ├── bb_entry.py         # Entry scanner + auto-add Paper
│   └── notify.py           # Gmail summary
├── data/
│   ├── watchlist.csv       # 17-stock universe
│   ├── positions_bb.csv    # Open positions (GitHub as data layer)
│   └── bb_trade_log.csv    # Trade history
├── requirements.txt
└── BB_Strategy_Reference.md

## Track Record (Paper — as of Jun 2026)

- Trades: 7 | Win rate: 7/7 | Avg return: +7.32% | Avg hold: ~51 days

## Environment Variables (DO Functions / .env)
GMAIL_SENDER=your@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
GMAIL_RECIPIENT=your@gmail.com
GITHUB_PAT=ghp_xxxxxxxxxxxx
GITHUB_REPO=finnyrajmann/nse-bb-system
