"""
NSE BB Swing Trader — DO Functions Entry Point
================================================
Uses only requests + standard library (no pip installs needed).
- Yahoo Finance API for price data
- GitHub REST API for reading/writing CSV data
- Gmail SMTP for notifications

Entry filter: Per-stock EMA50 slope regime check (no Nifty index filter)
"""

import os
import csv
import smtplib
import time
import base64
import math
from io import StringIO
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────
BB_PERIOD     = 20
BB_STD        = 2
EMA_SLOW      = 200
EMA_REGIME    = 50
STOP_LOSS_PCT = 10.0
POSITION_SIZE = 10000
SLEEP         = 0.5


# ─────────────────────────────────────────────
# YAHOO FINANCE
# ─────────────────────────────────────────────
def fetch_price_data(symbol, period='3mo'):
    ticker = symbol.upper().strip()
    if not ticker.startswith("^"):
        ticker = ticker + ".NS"

    range_map = {'3mo': '3mo', '6mo': '6mo', '1y': '1y'}
    params = {
        'range':    range_map.get(period, '3mo'),
        'interval': '1d',
        'events':   'history',
    }
    headers = {'User-Agent': 'Mozilla/5.0'}

    for host in ['query1', 'query2']:
        try:
            url = f"https://{host}.finance.yahoo.com/v8/finance/chart/{ticker}"
            r = requests.get(url, params=params, headers=headers, timeout=15)
            data = r.json()
            closes = data['chart']['result'][0]['indicators']['quote'][0]['close']
            closes = [c for c in closes if c is not None]
            if closes:
                return closes
        except Exception:
            continue
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
    window   = closes[-period:]
    mean     = sum(window) / period
    variance = sum((x - mean) ** 2 for x in window) / period
    std      = math.sqrt(variance)
    return {
        'bb_mid':   round(mean, 2),
        'bb_upper': round(mean + std_mult * std, 2),
        'bb_lower': round(mean - std_mult * std, 2),
    }


def get_indicators(symbol, period='1y'):
    """Get price + BB + EMA indicators for a symbol."""
    closes = fetch_price_data(symbol, period)
    if not closes or len(closes) < BB_PERIOD + 2:
        return None

    price  = round(closes[-1], 2)
    prev   = round(closes[-2], 2)
    change = round((price - prev) / prev * 100, 2)
    bb     = calc_bb(closes)
    if bb is None:
        return None
    stop   = round(price * (1 - STOP_LOSS_PCT / 100), 2)

    result = {
        'price':    price,
        'change':   change,
        'bb_upper': bb['bb_upper'],
        'bb_mid':   bb['bb_mid'],
        'bb_lower': bb['bb_lower'],
        'stop':     stop,
        'closes':   closes,
    }

    if len(closes) >= EMA_SLOW:
        ema200 = calc_ema(closes, EMA_SLOW)
        result['ema200']   = ema200
        result['above200'] = price > ema200 if ema200 else False
    else:
        result['ema200']   = None
        result['above200'] = False

    return result


def check_stock_regime(closes):
    """
    Per-stock regime check using EMA50 slope.
    Returns True if stock is in uptrend, False otherwise.
    """
    if len(closes) < 70:
        return False

    ema50_today = calc_ema(closes, EMA_REGIME)
    ema50_20d   = calc_ema(closes[:-20], EMA_REGIME)

    if ema50_today is None or ema50_20d is None:
        return False

    slope     = ema50_today - ema50_20d
    threshold = ema50_today * 0.005

    return slope > threshold


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
    data    = r.json()
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
    reader = csv.DictReader(StringIO(content))
    return list(reader)


def to_csv(rows, fieldnames):
    out    = StringIO()
    writer = csv.DictWriter(out, fieldnames=fieldnames, extrasaction='ignore')
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


# ─────────────────────────────────────────────
# BB EXIT
# ─────────────────────────────────────────────
def run_exit(positions, trade_log):
    exits         = []
    holds         = []
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

        if ind['price'] >= ind['bb_upper']:
            exit_type   = 'PROFIT'
            exit_reason = f"Price at BB Upper ({ind['bb_upper']})"
        elif ind['price'] <= stop_price:
            exit_type   = 'STOP'
            exit_reason = f"Stop loss hit ({stop_price})"

        result = {
            'Symbol':     symbol,
            'TrackType':  track_type,
            'EntryPrice': entry_price,
            'EntryDate':  pos['EntryDate'],
            'Quantity':   quantity,
            'Price':      ind['price'],
            'PnL':        pnl,
            'PnL%':       pnl_pct,
            'DaysHeld':   days_held,
            'ExitType':   exit_type,
            'ExitReason': exit_reason,
            'BBUpper':    ind['bb_upper'],
            'BBLower':    ind['bb_lower'],
            'Stop':       stop_price,
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
def run_entry(watchlist, positions):
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

        # Per-stock regime check — skip if stock not in uptrend
        if not check_stock_regime(ind['closes']):
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
            print(f"  Entry: {symbol} @ ₹{ind['price']} (BB Lower: {ind['bb_lower']})")

        time.sleep(SLEEP)

    return new_entries, positions


# ─────────────────────────────────────────────
# EMAIL
# ─────────────────────────────────────────────
def send_email(exits, entries, holds):
    sender    = os.environ.get('GMAIL_SENDER')
    password  = os.environ.get('GMAIL_APP_PASSWORD')
    recipient = os.environ.get('GMAIL_RECIPIENT')
    repo_name = os.environ.get('GITHUB_REPO')
    today     = datetime.now().strftime('%d %b %Y')
    subject   = f"NSE BB Trader — {today} | {len(entries)} new | {len(holds)} open"

    def table_style():
        return 'border-collapse:collapse;width:100%;font-family:Arial,sans-serif;font-size:14px;'

    def th_style():
        return 'background:#2c3e50;color:#fff;padding:8px 12px;text-align:left;'

    def td_style(align='left'):
        return f'padding:7px 12px;border-bottom:1px solid #eee;text-align:{align};'

    def section_header(title):
        return f'<h3 style="color:#2c3e50;margin:24px 0 8px 0;">{title}</h3>'

    html = f'''
    <div style="font-family:Arial,sans-serif;max-width:700px;margin:0 auto;">
    <h2 style="background:#2c3e50;color:#fff;padding:14px 18px;margin:0;border-radius:4px 4px 0 0;">
        📈 NSE BB Swing Trader — {today}
    </h2>
    '''

    # EXITS
    html += section_header(f'✅ Exits Today ({len(exits)})') if exits else section_header('✅ Exits: None today')
    if exits:
        html += f'<table style="{table_style()}"><thead><tr>'
        for col in ['', 'Symbol', 'P&L %', 'P&L ₹', 'Days', 'Reason']:
            html += f'<th style="{th_style()}">{col}</th>'
        html += '</tr></thead><tbody>'
        for r in exits:
            icon = '🟢' if r['PnL'] >= 0 else '🔴'
            html += f'''<tr>
                <td style="{td_style()}">{icon}</td>
                <td style="{td_style()}"><b>{r['Symbol']}</b></td>
                <td style="{td_style('right')}">{r['PnL%']:+.2f}%</td>
                <td style="{td_style('right')}">₹{r['PnL']:+.0f}</td>
                <td style="{td_style('right')}">{r['DaysHeld']}d</td>
                <td style="{td_style()}">{r['ExitReason']}</td>
            </tr>'''
        html += '</tbody></table>'

    # ENTRIES
    html += section_header(f'🔔 New Paper Entries ({len(entries)})') if entries else section_header('🔔 New Entries: None today')
    if entries:
        html += f'<table style="{table_style()}"><thead><tr>'
        for col in ['Symbol', 'Industry', 'Price ₹', 'Stop ₹', 'BB Lower ₹', 'BB Upper ₹', 'Trend']:
            html += f'<th style="{th_style()}">{col}</th>'
        html += '</tr></thead><tbody>'
        for e in entries:
            trend = '✅ Uptrend' if e['>EMA200'] else '⚠ Below EMA200'
            html += f'''<tr>
                <td style="{td_style()}"><b>{e['Symbol']}</b></td>
                <td style="{td_style()}">{e['Industry']}</td>
                <td style="{td_style('right')}">₹{e['Price']}</td>
                <td style="{td_style('right')}">₹{e['Stop']}</td>
                <td style="{td_style('right')}">₹{e['BB Lower']}</td>
                <td style="{td_style('right')}">₹{e['BB Upper']}</td>
                <td style="{td_style()}">{trend}</td>
            </tr>'''
        html += '</tbody></table>'

    # OPEN POSITIONS
    if holds:
        total_pnl = sum(r['PnL'] for r in holds)
        pnl_color = '#27ae60' if total_pnl >= 0 else '#e74c3c'
        html += section_header(
            f'📋 Open Positions ({len(holds)}) &nbsp;|&nbsp; '
            f'Total P&L: <span style="color:{pnl_color}">₹{total_pnl:+.0f}</span>'
        )
        html += f'<table style="{table_style()}"><thead><tr>'
        for col in ['', 'Symbol', 'Entry ₹', 'Price ₹', 'P&L %', 'P&L ₹', 'Days']:
            html += f'<th style="{th_style()}">{col}</th>'
        html += '</tr></thead><tbody>'
        for r in holds:
            icon = '🟢' if r['PnL'] >= 0 else '🔴'
            html += f'''<tr>
                <td style="{td_style()}">{icon}</td>
                <td style="{td_style()}"><b>{r['Symbol']}</b></td>
                <td style="{td_style('right')}">₹{r['EntryPrice']:.2f}</td>
                <td style="{td_style('right')}">₹{r['Price']:.2f}</td>
                <td style="{td_style('right')}">{r['PnL%']:+.2f}%</td>
                <td style="{td_style('right')}">₹{r['PnL']:+.0f}</td>
                <td style="{td_style('right')}">{r['DaysHeld']}d</td>
            </tr>'''
        html += '</tbody></table>'
    else:
        html += section_header('📋 Open Positions: None')

    # FOOTER
    html += f'''
    <p style="margin-top:24px;font-size:12px;color:#888;">
        <a href="https://github.com/{repo_name}/blob/master/data/bb_trade_log.csv" style="color:#2c3e50;">
            View trade log on GitHub
        </a><br>
        — NSE BB Trader (automated)
    </p>
    </div>
    '''

    msg = MIMEMultipart()
    msg['From']    = sender
    msg['To']      = recipient
    msg['Subject'] = subject
    msg.attach(MIMEText(html, 'html'))

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
        print("\n[1/5] Loading data from GitHub...")
        pos_content, pos_sha = github_get(repo_name, 'data/positions_bb.csv',  pat)
        log_content, log_sha = github_get(repo_name, 'data/bb_trade_log.csv',  pat)
        wl_content,  _       = github_get(repo_name, 'data/watchlist.csv',      pat)
        positions  = parse_csv(pos_content)
        trade_log  = parse_csv(log_content)
        watchlist  = parse_csv(wl_content)
        print(f"      {len(positions)} open positions | {len(watchlist)} watchlist stocks")

        # BB Exit
        print("\n[2/5] BB Exit Monitor...")
        exits, holds, positions, trade_log = run_exit(positions, trade_log)
        print(f"      {len(exits)} exit(s) | {len(holds)} holding")

        # BB Entry
        print("\n[3/5] BB Entry Scanner...")
        entries, positions = run_entry(watchlist, positions)
        print(f"      {len(entries)} new signal(s)")

        # Add today's entries to holds for email
        for e in entries:
            holds.append({
                'Symbol':     e['Symbol'],
                'EntryPrice': e['Price'],
                'Price':      e['Price'],
                'PnL':        0.0,
                'PnL%':       0.0,
                'DaysHeld':   0,
            })

        # Sync to GitHub
        print("\n[4/5] Syncing to GitHub...")
        commit_msg = f"Auto-update — {datetime.now().strftime('%Y-%m-%d')}"

        pos_fields = ['Symbol', 'EntryDate', 'EntryPrice', 'Quantity', 'TrackType']
        log_fields = ['Symbol', 'EntryDate', 'EntryPrice', 'Quantity', 'Capital',
                      'ExitDate', 'ExitPrice', 'PnL', 'PnL%', 'DaysHeld',
                      'ExitReason', 'TrackType']

        github_put(repo_name, 'data/positions_bb.csv', pat,
                   to_csv(positions, pos_fields), pos_sha, commit_msg)
        github_put(repo_name, 'data/bb_trade_log.csv', pat,
                   to_csv(trade_log, log_fields), log_sha, commit_msg)

        # Send email
        print("\n[5/5] Sending email...")
        send_email(exits, entries, holds)

        print("\n  Done.\n")
        return {"statusCode": 200, "body": "Pipeline complete"}

    except Exception as e:
        import traceback
        print(f"\n  ERROR: {str(e)}")
        print(traceback.format_exc())
        return {"statusCode": 500, "body": str(e)}
