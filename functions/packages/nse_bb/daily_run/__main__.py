"""
NSE BB Swing Trader — DO Functions Entry Point
================================================
Uses only requests + standard library (no pip installs needed).
- Yahoo Finance API for price data
- GitHub REST API for reading/writing CSV data
- Gmail SMTP for notifications

Entry filter: daily EMA200 freshness gate (price above EMA200 today) is
              now the SOLE entry trend filter — replaces the old per-stock
              EMA50 slope regime check, which was letting downtrend stocks
              through. Structural uptrend shape is enforced upstream by
              the shared watchlist screener (3-checkpoint EMA200 slope).
Target: price at/above BB Upper (unchanged) — this system stays
        mean-reversion, so it does NOT get a trailing-stop TARGET.
Stop:   TWO independent stop conditions now tracked side by side —
        the original fixed 10%-below-entry stop, and a NEW trailing
        10%-below-highest-daily-high-since-entry stop. Both are logged
        with distinct exit reasons so it's possible to see, over time,
        which one is actually catching more of the losing trades.

Design summary (locked, Sep 2026 rewrite):
- Watchlist swapped to the shared screener output (structurally uptrend,
  Nifty500, healthcare-excluded) — same source as the other systems.
- Entry trend filter REPLACED: the old EMA50 slope regime check is gone.
  The daily EMA200 freshness gate (price above EMA200 today) is now the
  only trend filter at entry time, matching the other systems.
- NEW trailing stop, tracked ALONGSIDE the existing fixed stop (not
  replacing it — this is the one system where both are kept, by design,
  to compare their effectiveness). Because the highest high since entry
  can never be below the entry price, the trailing-stop threshold is
  always >= the fixed-stop threshold — so a fixed-stop-only exit is not
  mathematically possible; a STOP_FIXED branch is kept for safety but
  should never actually fire. In practice every stop exit is either
  STOP_BOTH (price never rose after entry) or STOP_TRAIL (trailing
  caught it after some post-entry high).
- Below-EMA200 warning: an open position whose price falls below EMA200
  is NOT force-exited — only flagged in the email (mirrors the other
  systems), purely informational since BB's own exit logic doesn't use
  EMA200.
- Hit/miss split: PnL% > 3.0 -> hit, PnL% <= 3.0 -> miss, written to two
  separate trade logs instead of one combined log.
- Existing open positions carry forward into the new logic as-is.
- File naming: system code as SUFFIX everywhere —
  watchlist_bb.csv, positions_bb.csv (already suffixed),
  trade_log_hit_bb.csv, trade_log_miss_bb.csv. The old combined
  bb_trade_log.csv is retired (archived separately, not read by this
  script).
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
SYSTEM_CODE       = "bb"

BB_PERIOD         = 20
BB_STD            = 2
EMA_LONG          = 200    # daily freshness gate — the sole entry trend filter now
FIXED_STOP_PCT    = 10.0   # existing: 10% below entry price
TRAIL_STOP_PCT    = 10.0   # NEW: 10% below highest daily high since entry
POSITION_SIZE     = 10000
SLEEP             = 0.5
HIT_THRESHOLD_PCT = 3.0    # PnL% strictly greater than this -> hit, else -> miss

DATA_PERIOD       = "1y"   # sufficient for BB(20) and EMA200


# ─────────────────────────────────────────────
# YAHOO FINANCE
# ─────────────────────────────────────────────
def fetch_price_bars(symbol, period=DATA_PERIOD):
    """
    Fetch daily OHLC bars for a symbol.
    Returns a list of dicts: {'date', 'high', 'low', 'close'}
    ordered oldest -> newest. Returns None on failure.
    """
    ticker = symbol.upper().strip()
    if not ticker.startswith("^"):
        ticker = ticker + ".NS"

    params = {
        'range':    period,
        'interval': '1d',
        'events':   'history',
    }
    headers = {'User-Agent': 'Mozilla/5.0'}

    for host in ['query1', 'query2']:
        try:
            url = f"https://{host}.finance.yahoo.com/v8/finance/chart/{ticker}"
            r = requests.get(url, params=params, headers=headers, timeout=15)
            data = r.json()
            result = data['chart']['result'][0]
            timestamps = result['timestamp']
            quote = result['indicators']['quote'][0]
            highs  = quote['high']
            lows   = quote['low']
            closes = quote['close']

            bars = []
            for i, ts in enumerate(timestamps):
                c = closes[i]
                h = highs[i]
                l = lows[i]
                if c is None or h is None or l is None:
                    continue
                bars.append({
                    'date':  datetime.utcfromtimestamp(ts).date(),
                    'high':  h,
                    'low':   l,
                    'close': c,
                })
            if bars:
                return bars
        except Exception:
            continue
    return None


def calc_ema(values, period):
    """Calculate EMA over a list of closes (oldest -> newest)."""
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(values[:period]) / period
    for v in values[period:]:
        ema = v * k + ema * (1 - k)
    return round(ema, 2)


def calc_bb(closes, period=BB_PERIOD, std_mult=BB_STD):
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


def high_since(bars, entry_dt):
    """Highest daily HIGH from entry_dt (inclusive) to the most recent bar."""
    relevant = [b['high'] for b in bars if b['date'] >= entry_dt]
    if not relevant:
        return bars[-1]['high'] if bars else None
    return max(relevant)


def get_indicators(symbol, period=DATA_PERIOD):
    """Get price + BB + EMA9/30/200 + raw dated bars for a symbol."""
    bars = fetch_price_bars(symbol, period)
    if not bars or len(bars) < BB_PERIOD + 2:
        return None

    closes = [b['close'] for b in bars]
    price  = round(closes[-1], 2)

    bb = calc_bb(closes)
    if bb is None:
        return None

    return {
        'price':    price,
        'bb_upper': bb['bb_upper'],
        'bb_mid':   bb['bb_mid'],
        'bb_lower': bb['bb_lower'],
        'ema9':     calc_ema(closes, 9),
        'ema30':    calc_ema(closes, 30),
        'ema200':   calc_ema(closes, EMA_LONG),
        'bars':     bars,
    }


# ─────────────────────────────────────────────
# GITHUB REST API
# ─────────────────────────────────────────────
def github_get(repo, path, pat):
    """Read a file from GitHub. Returns (content, sha)."""
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
def run_exit(positions, hit_log, miss_log):
    """
    Check every open position for target / fixed-stop / trailing-stop exit.
    Returns (exits, holds, warnings, remaining_positions, hit_log, miss_log)
    """
    exits         = []
    holds         = []
    warnings      = []   # below-EMA200 — flag only, informational
    new_positions = []
    hit_log       = list(hit_log)
    miss_log      = list(miss_log)

    for pos in positions:
        symbol      = pos['Symbol']
        entry_price = float(pos['EntryPrice'])
        quantity    = int(pos['Quantity'])
        entry_date  = datetime.strptime(pos['EntryDate'], '%Y-%m-%d')
        track_type  = pos['TrackType']
        capital     = round(entry_price * quantity, 2)
        days_held   = (datetime.now() - entry_date).days

        fixed_stop_price = round(entry_price * (1 - FIXED_STOP_PCT / 100), 2)

        ind = get_indicators(symbol)
        if ind is None:
            new_positions.append(pos)
            time.sleep(SLEEP)
            continue

        price = ind['price']

        hi_since = high_since(ind['bars'], entry_date.date())
        trail_stop_price = round(hi_since * (1 - TRAIL_STOP_PCT / 100), 2) if hi_since else None

        fixed_hit = price <= fixed_stop_price
        trail_hit = trail_stop_price is not None and price <= trail_stop_price

        exit_type   = None
        exit_reason = None

        if price >= ind['bb_upper']:
            exit_type   = 'PROFIT'
            exit_reason = f"Price at/above BB Upper ({ind['bb_upper']})"
        elif fixed_hit and trail_hit:
            exit_type   = 'STOP_BOTH'
            exit_reason = (f"Fixed stop ({fixed_stop_price}) AND trailing stop "
                            f"({trail_stop_price}, high since entry {hi_since}) both hit")
        elif trail_hit:
            exit_type   = 'STOP_TRAIL'
            exit_reason = f"Trailing stop hit ({trail_stop_price}, high since entry {hi_since})"
        elif fixed_hit:
            # Not expected to occur (trail threshold is always >= fixed
            # threshold), kept as a safety branch.
            exit_type   = 'STOP_FIXED'
            exit_reason = f"Fixed stop hit ({fixed_stop_price})"

        pnl     = round((price - entry_price) * quantity, 2)
        pnl_pct = round((price - entry_price) / entry_price * 100, 2)

        if exit_type:
            record = {
                'Symbol':     symbol,
                'EntryDate':  pos['EntryDate'],
                'EntryPrice': entry_price,
                'Quantity':   quantity,
                'Capital':    capital,
                'ExitDate':   datetime.now().strftime('%Y-%m-%d'),
                'ExitPrice':  price,
                'PnL':        pnl,
                'PnL%':       pnl_pct,
                'DaysHeld':   days_held,
                'ExitReason': exit_reason,
                'TrackType':  track_type,
            }
            exits.append(record)
            if pnl_pct > HIT_THRESHOLD_PCT:
                hit_log.append(record)
            else:
                miss_log.append(record)
        else:
            new_positions.append(pos)
            holds.append({
                'Symbol':     symbol,
                'EntryPrice': entry_price,
                'Price':      price,
                'PnL':        pnl,
                'PnL%':       pnl_pct,
                'DaysHeld':   days_held,
            })

            if ind['ema200'] is not None and price < ind['ema200']:
                warnings.append({
                    'Symbol': symbol,
                    'Price':  price,
                    'EMA200': ind['ema200'],
                    'PnL%':   pnl_pct,
                })

        time.sleep(SLEEP)

    return exits, holds, warnings, new_positions, hit_log, miss_log


# ─────────────────────────────────────────────
# BB ENTRY
# ─────────────────────────────────────────────
def run_entry(watchlist, positions):
    """
    Watchlist is pre-vetted for STRUCTURAL uptrend shape by the separate
    periodic screener. Whether price is currently above EMA200 is
    re-checked fresh every run here — this is now the only entry trend
    filter (the old EMA50 slope regime check has been removed). Entry
    trigger: price at/below BB Lower.
    """
    open_symbols = {p['Symbol'].strip() for p in positions}
    new_entries  = []
    snapshots    = []

    for row in watchlist:
        symbol = row['Symbol'].strip()
        if symbol in open_symbols:
            continue

        ind = get_indicators(symbol)
        if ind is None:
            time.sleep(SLEEP)
            continue

        # Daily freshness gate — price must be above EMA200 TODAY.
        # This is now the ONLY entry trend filter (replaces the old
        # EMA50 slope regime check, which was letting downtrend stocks
        # through). Structural uptrend shape is already enforced
        # upstream by the shared watchlist screener.
        if ind['ema200'] is None or ind['price'] <= ind['ema200']:
            time.sleep(SLEEP)
            continue

        if ind['price'] <= ind['bb_lower']:
            quantity   = max(1, int(POSITION_SIZE / ind['price']))
            entry_date = datetime.now().strftime('%Y-%m-%d')

            positions.append({
                'Symbol':     symbol,
                'EntryDate':  entry_date,
                'EntryPrice': ind['price'],
                'Quantity':   quantity,
                'TrackType':  'Paper',
            })
            open_symbols.add(symbol)

            initial_stop = round(ind['price'] * (1 - FIXED_STOP_PCT / 100), 2)
            new_entries.append({
                'Symbol':   symbol,
                'Industry': row.get('Industry', ''),
                'Price':    ind['price'],
                'BBLower':  ind['bb_lower'],
                'BBUpper':  ind['bb_upper'],
                'Stop':     initial_stop,
            })
            snapshots.append({
                'Symbol':    symbol,
                'EntryDate': entry_date,
                'Price':     ind['price'],
                'BBLower':   ind['bb_lower'],
                'BBUpper':   ind['bb_upper'],
                'EMA9':      ind['ema9'],
                'EMA30':     ind['ema30'],
                'EMA200':    ind['ema200'],
            })
            print(f"  Entry: {symbol} @ Rs.{ind['price']} (BB Lower: {ind['bb_lower']})")

        time.sleep(SLEEP)

    return new_entries, positions, snapshots


# ─────────────────────────────────────────────
# EMAIL
# ─────────────────────────────────────────────
def send_email(exits, entries, holds, warnings, alltime_pnl, alltime_count,
               hit_count, miss_count):
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

    hits   = [e for e in exits if e['PnL%'] > HIT_THRESHOLD_PCT]
    misses = [e for e in exits if e['PnL%'] <= HIT_THRESHOLD_PCT]

    html = f'''
    <div style="font-family:Arial,sans-serif;max-width:700px;margin:0 auto;">
    <h2 style="background:#2c3e50;color:#fff;padding:14px 18px;margin:0;border-radius:4px 4px 0 0;">
        📈 NSE BB Swing Trader — {today}
    </h2>
    '''

    # EXITS
    html += section_header(
        f'✅ Exits Today ({len(exits)}) &mdash; {len(hits)} hit / {len(misses)} miss'
    ) if exits else section_header('✅ Exits: None today')
    if exits:
        html += f'<table style="{table_style()}"><thead><tr>'
        for col in ['', 'Symbol', 'P&L %', 'P&L Rs', 'Days', 'Reason']:
            html += f'<th style="{th_style()}">{col}</th>'
        html += '</tr></thead><tbody>'
        for r in exits:
            icon = '🟢' if r['PnL%'] > HIT_THRESHOLD_PCT else '🔴'
            html += f'''<tr>
                <td style="{td_style()}">{icon}</td>
                <td style="{td_style()}"><b>{r['Symbol']}</b></td>
                <td style="{td_style('right')}">{r['PnL%']:+.2f}%</td>
                <td style="{td_style('right')}">Rs.{r['PnL']:+.0f}</td>
                <td style="{td_style('right')}">{r['DaysHeld']}d</td>
                <td style="{td_style()}">{r['ExitReason']}</td>
            </tr>'''
        html += '</tbody></table>'

    # ENTRIES
    html += section_header(f'🔔 New Paper Entries ({len(entries)})') \
        if entries else section_header('🔔 New Entries: None today')
    if entries:
        html += f'<table style="{table_style()}"><thead><tr>'
        for col in ['Symbol', 'Industry', 'Price Rs', 'Stop Rs', 'BB Lower Rs', 'BB Upper Rs']:
            html += f'<th style="{th_style()}">{col}</th>'
        html += '</tr></thead><tbody>'
        for e in entries:
            html += f'''<tr>
                <td style="{td_style()}"><b>{e['Symbol']}</b></td>
                <td style="{td_style()}">{e['Industry']}</td>
                <td style="{td_style('right')}">Rs.{e['Price']}</td>
                <td style="{td_style('right')}">Rs.{e['Stop']}</td>
                <td style="{td_style('right')}">Rs.{e['BBLower']}</td>
                <td style="{td_style('right')}">Rs.{e['BBUpper']}</td>
            </tr>'''
        html += '</tbody></table>'

    # OPEN POSITIONS
    if holds:
        total_pnl = sum(r['PnL'] for r in holds)
        pnl_color = '#27ae60' if total_pnl >= 0 else '#e74c3c'
        html += section_header(
            f'📋 Open Positions ({len(holds)}) &nbsp;|&nbsp; '
            f'Total P&L: <span style="color:{pnl_color}">Rs.{total_pnl:+.0f}</span>'
        )
        html += f'<table style="{table_style()}"><thead><tr>'
        for col in ['', 'Symbol', 'Entry Rs', 'Price Rs', 'P&L %', 'P&L Rs', 'Days']:
            html += f'<th style="{th_style()}">{col}</th>'
        html += '</tr></thead><tbody>'
        for r in holds:
            icon = '🟢' if r['PnL'] >= 0 else '🔴'
            html += f'''<tr>
                <td style="{td_style()}">{icon}</td>
                <td style="{td_style()}"><b>{r['Symbol']}</b></td>
                <td style="{td_style('right')}">Rs.{r['EntryPrice']:.2f}</td>
                <td style="{td_style('right')}">Rs.{r['Price']:.2f}</td>
                <td style="{td_style('right')}">{r['PnL%']:+.2f}%</td>
                <td style="{td_style('right')}">Rs.{r['PnL']:+.0f}</td>
                <td style="{td_style('right')}">{r['DaysHeld']}d</td>
            </tr>'''
        html += '</tbody></table>'
    else:
        html += section_header('📋 Open Positions: None')

    # BELOW-EMA200 WARNING (informational only)
    if warnings:
        html += section_header(f'⚠️ Below EMA200 ({len(warnings)})')
        html += f'<table style="{table_style()}"><thead><tr>'
        for col in ['Symbol', 'Price Rs', 'EMA200 Rs', 'P&L %']:
            html += f'<th style="{th_style()}">{col}</th>'
        html += '</tr></thead><tbody>'
        for w in warnings:
            html += f'''<tr>
                <td style="{td_style()}"><b>{w['Symbol']}</b></td>
                <td style="{td_style('right')}">Rs.{w['Price']:.2f}</td>
                <td style="{td_style('right')}">Rs.{w['EMA200']:.2f}</td>
                <td style="{td_style('right')}">{w['PnL%']:+.2f}%</td>
            </tr>'''
        html += '</tbody></table>'

    # CUMULATIVE TRADE LOG P&L
    at_color = '#27ae60' if alltime_pnl >= 0 else '#e74c3c'
    hit_rate = f'{(hit_count / alltime_count * 100):.0f}%' if alltime_count else 'N/A'
    html += section_header('📊 All-Time Trade Log')
    html += f'''
    <table style="{table_style()}"><tbody>
        <tr>
            <td style="{td_style()}">Closed trades</td>
            <td style="{td_style('right')}">{alltime_count} ({hit_count} hit / {miss_count} miss, {hit_rate} hit rate)</td>
        </tr>
        <tr>
            <td style="{td_style()}">Cumulative P&amp;L</td>
            <td style="{td_style('right')}"><span style="color:{at_color}"><b>Rs.{alltime_pnl:+,.0f}</b></span></td>
        </tr>
    </tbody></table>
    '''

    # FOOTER
    html += f'''
    <p style="margin-top:24px;font-size:12px;color:#888;">
        <a href="https://github.com/{repo_name}/blob/master/data/trade_log_hit_{SYSTEM_CODE}.csv" style="color:#2c3e50;">
            View hit log
        </a> &nbsp;|&nbsp;
        <a href="https://github.com/{repo_name}/blob/master/data/trade_log_miss_{SYSTEM_CODE}.csv" style="color:#2c3e50;">
            View miss log
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

    pos_path      = f'data/positions_{SYSTEM_CODE}.csv'
    hit_log_path  = f'data/trade_log_hit_{SYSTEM_CODE}.csv'
    miss_log_path = f'data/trade_log_miss_{SYSTEM_CODE}.csv'
    wl_path       = f'data/watchlist_{SYSTEM_CODE}.csv'
    snap_path     = f'data/entry_snapshot_{SYSTEM_CODE}.csv'

    try:
        print("\n[1/5] Loading data from GitHub...")
        pos_content, pos_sha       = github_get(repo_name, pos_path, pat)
        hitlog_content, hit_sha    = github_get(repo_name, hit_log_path, pat)
        misslog_content, miss_sha  = github_get(repo_name, miss_log_path, pat)
        wl_content, _              = github_get(repo_name, wl_path, pat)
        snap_content, snap_sha     = github_get(repo_name, snap_path, pat)

        positions       = parse_csv(pos_content)
        hit_log         = parse_csv(hitlog_content)
        miss_log        = parse_csv(misslog_content)
        watchlist       = parse_csv(wl_content)
        entry_snapshots = parse_csv(snap_content)
        print(f"      {len(positions)} open positions | {len(watchlist)} watchlist stocks")

        print("\n[2/5] BB Exit Monitor...")
        exits, holds, warnings, positions, hit_log, miss_log = run_exit(positions, hit_log, miss_log)
        print(f"      {len(exits)} exit(s) | {len(holds)} holding | {len(warnings)} below-EMA200 warning(s)")

        print("\n[3/5] BB Entry Scanner...")
        entries, positions, new_snapshots = run_entry(watchlist, positions)
        entry_snapshots.extend(new_snapshots)
        print(f"      {len(entries)} new signal(s)")

        # Add today's entries to holds for email (0-day P&L placeholders)
        for e in entries:
            holds.append({
                'Symbol':     e['Symbol'],
                'EntryPrice': e['Price'],
                'Price':      e['Price'],
                'PnL':        0.0,
                'PnL%':       0.0,
                'DaysHeld':   0,
            })

        print("\n[4/5] Syncing to GitHub...")
        commit_msg = f"Auto-update — {datetime.now().strftime('%Y-%m-%d')}"

        pos_fields  = ['Symbol', 'EntryDate', 'EntryPrice', 'Quantity', 'TrackType']
        log_fields  = ['Symbol', 'EntryDate', 'EntryPrice', 'Quantity', 'Capital',
                       'ExitDate', 'ExitPrice', 'PnL', 'PnL%', 'DaysHeld',
                       'ExitReason', 'TrackType']
        snap_fields = ['Symbol', 'EntryDate', 'Price', 'BBLower', 'BBUpper',
                       'EMA9', 'EMA30', 'EMA200']

        github_put(repo_name, pos_path, pat,
                   to_csv(positions, pos_fields), pos_sha, commit_msg)
        github_put(repo_name, hit_log_path, pat,
                   to_csv(hit_log, log_fields), hit_sha, commit_msg)
        github_put(repo_name, miss_log_path, pat,
                   to_csv(miss_log, log_fields), miss_sha, commit_msg)
        github_put(repo_name, snap_path, pat,
                   to_csv(entry_snapshots, snap_fields), snap_sha, commit_msg)

        alltime_pnl = (sum(float(r['PnL']) for r in hit_log) +
                       sum(float(r['PnL']) for r in miss_log))
        alltime_count = len(hit_log) + len(miss_log)

        print("\n[5/5] Sending email...")
        send_email(exits, entries, holds, warnings, alltime_pnl, alltime_count,
                   len(hit_log), len(miss_log))

        print("\n  Done.\n")
        return {"statusCode": 200, "body": "Pipeline complete"}

    except Exception as e:
        import traceback
        print(f"\n  ERROR: {str(e)}")
        print(traceback.format_exc())
        return {"statusCode": 500, "body": str(e)}
