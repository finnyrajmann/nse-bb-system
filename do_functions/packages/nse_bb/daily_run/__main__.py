"""
NSE BB Swing Trader — DO Functions Entry Point
================================================
Uses only requests + standard library (no pip installs needed).
- Yahoo Finance API for price data
- GitHub REST API for reading/writing CSV data
- Gmail SMTP for notifications
"""

import os
import json
import csv
import smtplib
import time
import base64
import math
from io import StringIO
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────
BB_PERIOD     = 20
BB_STD        = 2
EMA_SLOW      = 200
STOP_LOSS_PCT = 10.0
POSITION_SIZE = 10000
SLEEP         = 0.5


# ─────────────────────────────────────────────
# YAHOO FINANCE — direct API
# ─────────────────────────────────────────────
def fetch_price_data(symbol, period='3mo'):
    """Fetch OHLCV data from Yahoo Finance API."""
    ticker = symbol.upper().strip()
    if not ticker.startswith("^"):
        ticker = ticker + ".NS"
    url    = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    
    range_map = {'3mo': '3mo', '1y': '1y'}
    params = {
        'range':    range_map.get(period, '3mo'),
        'interval': '1d',
        'events':   'history',
    }
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    try:
        r = requests.get(url, params=params, headers=headers, timeout=15)
        data = r.json()
        result = data['chart']['result'][0]
        closes = result['indicators']['quote'][0]['close']
        # Filter out None values
        closes = [c for c in closes if c is not None]
        return closes
    except Exception as e:
        return None


def calc_ema(values, period):
    """Calculate EMA."""
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(values[:period]) / period
    for v in values[period:]:
        ema = v * k + ema * (1 - k)
    return round(ema, 2)


def calc_bb(closes, period=20, std_mult=2):
    """Calculate Bollinger Bands from last N closes."""
    if len(closes) < period + 2:
        return None
    window  = closes[-period:]
    mean    = sum(window) / period
    variance = sum((x - mean) ** 2 for x in window) / period
    std     = math.sqrt(variance)
    return {
        'bb_mid':   round(mean, 2),
        'bb_upper': round(mean + std_mult * std, 2),
        'bb_lower': round(mean - std_mult * std, 2),
    }


def get_indicators(symbol, period='3mo'):
    """Get price + BB indicators for a symbol."""
    closes = fetch_price_data(symbol, period)
    if not closes or len(closes) < BB_PERIOD + 2:
        return None
    
    price  = round(closes[-1], 2)
    prev   = round(closes[-2], 2)
    change = round((price - prev) / prev * 100, 2)
    bb     = calc_bb(closes)
    stop   = round(price * (1 - STOP_LOSS_PCT / 100), 2)
    
    result = {
        'price':    price,
        'change':   change,
        'bb_upper': bb['bb_upper'],
        'bb_mid':   bb['bb_mid'],
        'bb_lower': bb['bb_lower'],
        'stop':     stop,
    }
    
    if period == '1y' and len(closes) >= EMA_SLOW:
        ema200 = calc_ema(closes, EMA_SLOW)
        result['ema200']   = ema200
        result['above200'] = price > ema200 if ema200 else False
    
    return result


# ─────────────────────────────────────────────
# GITHUB REST API
# ─────────────────────────────────────────────
def github_get(repo, path, pat):
    """Read a file from GitHub."""
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {
        'Authorization': f'token {pat}',
        'Accept': 'application/vnd.github.v3+json',
    }
    r = requests.get(url, headers=headers, timeout=15)
    r.raise_for_status()
    data = r.json()
    content = base64.b64decode(data['content']).decode('utf-8')
    return content, data['sha']


def github_put(repo, path, pat, content, sha, message):
    """Write a file to GitHub."""
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {
        'Authorization': f'token {pat}',
        'Accept': 'application/vnd.github.v3+json',
    }
    payload = {
        'message': message,
        'content': base64.b64encode(content.encode('utf-8')).decode('utf-8'),
        'sha':     sha,
    }
    r = requests.put(url, headers=headers, json=payload, timeout=15)
    r.raise_for_status()
    return True


def parse_csv(content):
    """Parse CSV string into list of dicts."""
    reader = csv.DictReader(StringIO(content))
    return list(reader)


def to_csv(rows, fieldnames):
    """Convert list of dicts to CSV string."""
    out = StringIO()
    writer = csv.DictWriter(out, fieldnames=fieldnames, extrasaction='ignore')
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


# ─────────────────────────────────────────────
# REGIME CHECK
# ─────────────────────────────────────────────
def check_regime():
    closes = fetch_price_data('^NSEI', '3mo')
    if not closes or len(closes) < 52:
        return {'regime': 'PAUSE', 'nifty_price': None, 'ema50': None,
                'nifty_change': None, 'message': 'Could not fetch Nifty — defaulting to PAUSE'}

    price  = round(closes[-1], 2)
    prev   = round(closes[-2], 2)
    change = round((price - prev) / prev * 100, 2)

    # Calculate EMA50 today and 20 days ago
    ema50_today = calc_ema(closes, 50)
    ema50_20d   = calc_ema(closes[:-20], 50)

    # Slope and threshold
    slope     = round(ema50_today - ema50_20d, 2)
    threshold = round(ema50_today * 0.005, 2)

    # Trend decision
    if slope > threshold and price > ema50_today:
        regime  = 'GO'
        message = f'Nifty {price} > EMA50 {ema50_today} | Slope +{slope} — uptrend, entries allowed'
    elif slope < -threshold and price < ema50_today:
        regime  = 'DEFENSIVE'
        message = f'Nifty {price} < EMA50 {ema50_today} | Slope {slope} — downtrend, protecting positions'
    else:
        regime  = 'PAUSE'
        message = f'Nifty {price} ~ EMA50 {ema50_today} | Slope {slope} — sideways, no new entries'

    return {
        'regime':       regime,
        'nifty_price':  price,
        'ema50':        ema50_today,
        'slope':        slope,
        'nifty_change': change,
        'message':      message,
    }


# ─────────────────────────────────────────────
# BB EXIT
# ─────────────────────────────────────────────
def run_exit(positions, trade_log, regime):
    exits        = []
    holds        = []
    new_positions = []

    for pos in positions:
        symbol      = pos['Symbol']
        entry_price = float(pos['EntryPrice'])
        quantity    = int(pos['Quantity'])
        entry_date  = datetime.strptime(pos['EntryDate'], '%Y-%m-%d')
        days_held   = (datetime.now() - entry_date).days
        track_type  = pos['TrackType']
        stop_price  = round(entry_price * (1 - STOP_LOSS_PCT / 100), 2)

        ind = get_indicators(symbol)
        if ind is None:
            new_positions.append(pos)
            continue

        pnl     = round((ind['price'] - entry_price) * quantity, 2)
        pnl_pct = round((ind['price'] - entry_price) / entry_price * 100, 2)

        exit_type   = None
        exit_reason = None

        # Normal exit conditions
        if ind['price'] >= ind['bb_upper']:
            exit_type   = 'PROFIT'
            exit_reason = f"Price at BB Upper ({ind['bb_upper']})"
        elif ind['price'] <= stop_price:
            exit_type   = 'STOP'
            exit_reason = f"Stop loss hit ({stop_price})"
        # DEFENSIVE regime — protect gains
        elif regime == 'DEFENSIVE' and pnl_pct >= 3.0:
            exit_type   = 'PROFIT'
            exit_reason = f"Regime DEFENSIVE — protecting gains ({pnl_pct:+.2f}%)"

        result = {
            'Symbol': symbol, 'TrackType': track_type,
            'EntryPrice': entry_price, 'EntryDate': pos['EntryDate'],
            'Quantity': quantity, 'Price': ind['price'],
            'PnL': pnl, 'PnL%': pnl_pct, 'DaysHeld': days_held,
            'ExitType': exit_type, 'ExitReason': exit_reason,
            'BBUpper': ind['bb_upper'], 'BBLower': ind['bb_lower'],
            'Stop': stop_price,
        }

        if exit_type:
            exits.append(result)
            trade_log.append({
                'Symbol':     symbol,
                'EntryDate':  pos['EntryDate'],
                'EntryPrice': entry_price,
                'Quantity':   quantity,
                'Capital':    round(entry_price * quantity, 2),
                'ExitDate':   datetime.now().strftime('%Y-%m-%d'),
                'ExitPrice':  ind['price'],
                'PnL':        pnl,
                'PnL%':       pnl_pct,
                'DaysHeld':   days_held,
                'ExitReason': exit_reason,
                'TrackType':  track_type,
            })
        else:
            holds.append(result)
            new_positions.append(pos)

        time.sleep(SLEEP)

    return exits, holds, new_positions, trade_log


# ─────────────────────────────────────────────
# BB ENTRY
# ─────────────────────────────────────────────
def run_entry(watchlist, positions, regime):
    if regime != 'GO':
        return [], positions

    open_symbols = {p['Symbol'].strip() for p in positions}
    new_entries  = []

    for row in watchlist:
        symbol = row['Symbol'].strip()
        if symbol in open_symbols:
            continue

        ind = get_indicators(symbol, period='1y')
        if ind is None:
            time.sleep(SLEEP)
            continue

        if ind['price'] <= ind['bb_lower']:
            quantity = max(1, int(POSITION_SIZE / ind['price']))
            positions.append({
                'Symbol':     symbol,
                'EntryDate':  datetime.now().strftime('%Y-%m-%d'),
                'EntryPrice': ind['price'],
                'Quantity':   quantity,
                'TrackType':  'Paper',
            })
            open_symbols.add(symbol)
            new_entries.append({
                'Symbol':   symbol,
                'Industry': row.get('Industry', ''),
                'Price':    ind['price'],
                'BB Lower': ind['bb_lower'],
                'BB Upper': ind['bb_upper'],
                'EMA200':   ind.get('ema200', 0),
                '>EMA200':  ind.get('above200', False),
                'Stop':     ind['stop'],
            })

        time.sleep(SLEEP)

    return new_entries, positions


# ─────────────────────────────────────────────
# NOTIFY
# ─────────────────────────────────────────────
def send_email(regime_result, exits, entries, holds):
    sender    = os.environ.get('GMAIL_SENDER')
    password  = os.environ.get('GMAIL_APP_PASSWORD')
    recipient = os.environ.get('GMAIL_RECIPIENT')
    repo_name = os.environ.get('GITHUB_REPO')
    today     = datetime.now().strftime('%d %b %Y')
    regime    = regime_result['regime']
    icon = '🟢' if regime == 'GO' else '🟡' if regime == 'PAUSE' else '🔴'
    subject   = f"NSE BB Trader — {today} | Regime: {icon} {regime}"

    lines = []
    lines.append(f"NSE BB SWING TRADER — {today}")
    lines.append("=" * 50)
    lines.append(f"\n📊 MARKET REGIME: {icon} {regime}")
    lines.append(f"   Nifty: {regime_result['nifty_price']} ({regime_result['nifty_change']}%)  |  EMA50: {regime_result['ema50']}  |  Slope: {regime_result['slope']}")
    lines.append(f"   {regime_result['message']}")

    lines.append(f"\n{'─'*50}")
    if exits:
        lines.append(f"\n✅ EXITS ACTIONED TODAY ({len(exits)})")
        for r in exits:
            icon2 = '🟢' if r['PnL'] >= 0 else '🔴'
            lines.append(f"   {icon2} {r['Symbol']:<12} {r['PnL%']:+.2f}%  ₹{r['PnL']:+.0f}  ({r['DaysHeld']}d)")
    else:
        lines.append(f"\n✅ EXITS: None today")

    lines.append(f"\n{'─'*50}")
    if entries:
        lines.append(f"\n🔔 NEW PAPER ENTRIES — CONSIDER FOR REAL TRADE ({len(entries)})")
        for e in entries:
            trend = '✅ Uptrend' if e['>EMA200'] else '⚠ Below EMA200'
            lines.append(f"\n   ▶ {e['Symbol']} ({e['Industry']})")
            lines.append(f"     Price: ₹{e['Price']}  |  Stop: ₹{e['Stop']}  |  {trend}")
            lines.append(f"     BB Lower: ₹{e['BB Lower']}  →  BB Upper: ₹{e['BB Upper']}")
    elif regime == 'CAUTIOUS':
        lines.append(f"\n🔔 NEW ENTRIES: None — Cautious mode, only EMA200 stocks scanned")
    else:
        lines.append(f"\n🔔 NEW ENTRIES: None today")

    lines.append(f"\n{'─'*50}")
    if holds:
        total_pnl = sum(r['PnL'] for r in holds)
        lines.append(f"\n📋 OPEN POSITIONS ({len(holds)})  |  Total P&L: ₹{total_pnl:+.0f}")
        lines.append(f"   {'Symbol':<12} {'Entry':>8} {'Price':>8} {'P&L%':>7} {'P&L₹':>8} {'Days':>5}")
        lines.append(f"   {'-'*55}")
        for r in holds:
            icon3 = '🟢' if r['PnL'] >= 0 else '🔴'
            lines.append(f"   {icon3} {r['Symbol']:<12} "
                        f"₹{r['EntryPrice']:>7.2f} ₹{r['Price']:>7.2f} "
                        f"{r['PnL%']:>+7.2f}% ₹{r['PnL']:>+8.0f} {r['DaysHeld']:>4}d")

    lines.append(f"\n{'─'*50}")
    lines.append(f"\nTrade log: https://github.com/{repo_name}/blob/master/data/bb_trade_log.csv")
    lines.append(f"\n— NSE BB Trader (automated)")

    body = '\n'.join(lines)
    msg  = MIMEMultipart()
    msg['From']    = sender
    msg['To']      = recipient
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(sender, password)
        server.sendmail(sender, recipient, msg.as_string())
    print(f"  Email sent to {recipient}")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main(args):
    print("\n" + "="*50)
    print("  NSE BB SWING TRADER — DO Functions Run")
    print("="*50)

    pat       = os.environ.get('GITHUB_PAT')
    repo_name = os.environ.get('GITHUB_REPO')

    try:
        # Load data from GitHub
        print("\n[1/6] Loading data from GitHub...")
        pos_content,  pos_sha  = github_get(repo_name, 'data/positions_bb.csv',  pat)
        log_content,  log_sha  = github_get(repo_name, 'data/bb_trade_log.csv',  pat)
        wl_content,   _        = github_get(repo_name, 'data/watchlist.csv',      pat)
        positions  = parse_csv(pos_content)
        trade_log  = parse_csv(log_content)
        watchlist  = parse_csv(wl_content)
        print(f"      {len(positions)} open positions | {len(watchlist)} watchlist stocks")

        # Regime check
        print("\n[2/6] Regime Check...")
        regime_result = check_regime()
        print(f"      {regime_result['message']}")

        # BB Exit
        print("\n[3/6] BB Exit Monitor...")
        exits, holds, positions, trade_log = run_exit(positions, trade_log, regime_result['regime'])
        print(f"      {len(exits)} exit(s) | {len(holds)} holding")

        # BB Entry
        print("\n[4/6] BB Entry Scanner...")
        entries, positions = run_entry(watchlist, positions, regime_result['regime'])
        print(f"      {len(entries)} new signal(s)")

        # Sync to GitHub
        print("\n[5/6] Syncing to GitHub...")
        commit_msg = f"Auto-update — {datetime.now().strftime('%Y-%m-%d')}"

        pos_fields = ['Symbol','EntryDate','EntryPrice','Quantity','TrackType']
        log_fields = ['Symbol','EntryDate','EntryPrice','Quantity','Capital',
                      'ExitDate','ExitPrice','PnL','PnL%','DaysHeld','ExitReason','TrackType']

        github_put(repo_name, 'data/positions_bb.csv', pat,
                   to_csv(positions, pos_fields), pos_sha, commit_msg)
        github_put(repo_name, 'data/bb_trade_log.csv', pat,
                   to_csv(trade_log, log_fields), log_sha, commit_msg)

        # Send email
        print("\n[6/6] Sending email...")
        send_email(regime_result, exits, entries, holds)

        print("\n  Done.\n")
        return {"statusCode": 200, "body": "Pipeline complete"}

    except Exception as e:
        import traceback
        print(f"\n  ERROR: {str(e)}")
        print(traceback.format_exc())
        return {"statusCode": 500, "body": str(e)}
