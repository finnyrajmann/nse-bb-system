"""
Notify
=======
Sends a daily Gmail summary with:
    - Market regime status
    - Exits actioned today
    - New paper entries (highlighted)
    - Open positions P&L snapshot
"""

import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from dotenv import load_dotenv

# Load from ~/.env_nse_bb
load_dotenv(os.path.expanduser("~/.env_nse_bb"))

GMAIL_SENDER    = os.getenv("GMAIL_SENDER")
GMAIL_PASSWORD  = os.getenv("GMAIL_APP_PASSWORD")
GMAIL_RECIPIENT = os.getenv("GMAIL_RECIPIENT")


def build_email(regime_result, exit_results, entry_results, hold_results):
    today     = datetime.now().strftime("%d %b %Y")
    regime    = regime_result['regime']
    nifty     = regime_result.get('nifty_price', 'N/A')
    ema50     = regime_result.get('ema50', 'N/A')
    nifty_chg = regime_result.get('nifty_change', 'N/A')

    regime_icon  = "🟢" if regime == "GO" else "🔴"
    subject      = f"NSE BB Trader — {today} | Regime: {regime_icon} {regime}"

    # ── Plain text body ──
    lines = []
    lines.append(f"NSE BB SWING TRADER — {today}")
    lines.append("=" * 50)

    # Regime
    lines.append(f"\n📊 MARKET REGIME: {regime_icon} {regime}")
    lines.append(f"   Nifty: {nifty} ({nifty_chg}%)  |  EMA50: {ema50}")
    lines.append(f"   {regime_result['message']}")

    # Exits
    lines.append(f"\n{'─'*50}")
    if exit_results:
        lines.append(f"\n✅ EXITS ACTIONED TODAY ({len(exit_results)})")
        for r in exit_results:
            icon = "🟢" if r['PnL'] >= 0 else "🔴"
            lines.append(f"   {icon} {r['Symbol']:<12} "
                        f"{r['PnL%']:+.2f}%  ₹{r['PnL']:+.0f}  "
                        f"({r['DaysHeld']}d)  — {r['ExitReason']}")
    else:
        lines.append(f"\n✅ EXITS: None today")

    # New entries
    lines.append(f"\n{'─'*50}")
    if entry_results:
        lines.append(f"\n🔔 NEW PAPER ENTRIES — ACTION NEEDED ({len(entry_results)})")
        lines.append(f"   Consider placing real trades for the following:")
        for e in entry_results:
            trend = "✅ Uptrend" if e['>EMA200'] else "⚠ Below EMA200"
            lines.append(f"\n   ▶ {e['Symbol']} ({e['Industry']})")
            lines.append(f"     Price    : ₹{e['Price']}")
            lines.append(f"     BB Lower : ₹{e['BB Lower']}")
            lines.append(f"     BB Upper : ₹{e['BB Upper']}")
            lines.append(f"     Stop     : ₹{e['Stop']}")
            lines.append(f"     Trend    : {trend}")
    elif regime == "PAUSE":
        lines.append(f"\n🔔 NEW ENTRIES: None — Market in PAUSE mode")
    else:
        lines.append(f"\n🔔 NEW ENTRIES: None today")

    # Open positions
    lines.append(f"\n{'─'*50}")
    if hold_results:
        total_pnl = sum(r['PnL'] for r in hold_results)
        lines.append(f"\n📋 OPEN POSITIONS ({len(hold_results)})  |  Total P&L: ₹{total_pnl:+.0f}")
        lines.append(f"   {'Symbol':<12} {'Entry':>8} {'Price':>8} {'P&L%':>7} {'P&L₹':>8} {'Days':>5}")
        lines.append(f"   {'-'*55}")
        for r in hold_results:
            icon = "🟢" if r['PnL'] >= 0 else "🔴"
            lines.append(f"   {icon} {r['Symbol']:<12} "
                        f"₹{r['EntryPrice']:>7.2f} "
                        f"₹{r['Price']:>7.2f} "
                        f"{r['PnL%']:>+7.2f}% "
                        f"₹{r['PnL']:>+8.0f} "
                        f"{r['DaysHeld']:>4}d")
    else:
        lines.append(f"\n📋 OPEN POSITIONS: None")

    lines.append(f"\n{'─'*50}")
    lines.append(f"\nTrade log: https://github.com/{os.getenv('GITHUB_REPO')}/blob/master/data/bb_trade_log.csv")
    lines.append(f"\n— NSE BB Trader (automated)")

    return subject, "\n".join(lines)


def send_email(subject, body):
    msg = MIMEMultipart()
    msg['From']    = GMAIL_SENDER
    msg['To']      = GMAIL_RECIPIENT
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(GMAIL_SENDER, GMAIL_PASSWORD)
            server.sendmail(GMAIL_SENDER, GMAIL_RECIPIENT, msg.as_string())
        print(f"  Email sent to {GMAIL_RECIPIENT}")
        return True
    except Exception as e:
        print(f"  Email failed: {str(e)}")
        return False


def run(regime_result, exit_results, entry_results, hold_results):
    print(f"\nNotify — building summary email...")
    subject, body = build_email(regime_result, exit_results, entry_results, hold_results)
    print(f"  Subject: {subject}")
    send_email(subject, body)


if __name__ == "__main__":
    # Test with dummy data
    regime_result = {
        "regime":       "PAUSE",
        "nifty_price":  23383.9,
        "nifty_change": -0.39,
        "ema50":        23815.44,
        "message":      "Nifty below EMA50 — no new entries today"
    }
    exit_results  = []
    entry_results = []
    hold_results  = [
        {'Symbol':'PFC',       'EntryPrice':387.0,  'Price':416.5,  'PnL':737,  'PnL%':7.62,  'DaysHeld':72, 'ExitType':None, 'ExitReason':None},
        {'Symbol':'DRREDDY',   'EntryPrice':1253.3, 'Price':1262.2, 'PnL':62,   'PnL%':0.71,  'DaysHeld':71, 'ExitType':None, 'ExitReason':None},
        {'Symbol':'TORNTPOWER','EntryPrice':1362.8, 'Price':1426.3, 'PnL':444,  'PnL%':4.66,  'DaysHeld':71, 'ExitType':None, 'ExitReason':None},
        {'Symbol':'NTPC',      'EntryPrice':358.8,  'Price':367.5,  'PnL':235,  'PnL%':2.42,  'DaysHeld':58, 'ExitType':None, 'ExitReason':None},
    ]
    run(regime_result, exit_results, entry_results, hold_results)
