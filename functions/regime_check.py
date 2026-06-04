"""
Regime Check
=============
Fetches Nifty50 daily data and checks if price is above EMA50.

Returns:
    GO       — Nifty > EMA50, full scan
    CAUTIOUS — Nifty < EMA50, scan only stocks above EMA200
"""

import yfinance as yf


def check_regime():
    try:
        ticker = yf.Ticker("^NSEI")
        df     = ticker.history(period="3mo", interval="1d")

        if df.empty or len(df) < 52:
            return {
                "regime":       "CAUTIOUS",
                "nifty_price":  None,
                "ema50":        None,
                "nifty_change": None,
                "message":      "Could not fetch Nifty — defaulting to CAUTIOUS"
            }

        close  = df["Close"]
        ema50  = round(float(close.ewm(span=50, adjust=False).mean().iloc[-1]), 2)
        price  = round(float(close.iloc[-1]), 2)
        change = round((price - float(close.iloc[-2])) / float(close.iloc[-2]) * 100, 2)

        if price > ema50:
            return {
                "regime":       "GO",
                "nifty_price":  price,
                "ema50":        ema50,
                "nifty_change": change,
                "message":      f"Nifty {price} > EMA50 {ema50} — full scan, all stocks"
            }
        else:
            return {
                "regime":       "CAUTIOUS",
                "nifty_price":  price,
                "ema50":        ema50,
                "nifty_change": change,
                "message":      f"Nifty {price} < EMA50 {ema50} — cautious, EMA200 stocks only"
            }

    except Exception as e:
        return {
            "regime":       "CAUTIOUS",
            "nifty_price":  None,
            "ema50":        None,
            "nifty_change": None,
            "message":      f"Regime check failed: {str(e)} — defaulting to CAUTIOUS"
        }


if __name__ == "__main__":
    result = check_regime()
    print(f"\nRegime Check")
    print(f"  Status  : {result['regime']}")
    print(f"  Nifty   : {result['nifty_price']} ({result.get('nifty_change', 'N/A')}%)")
    print(f"  EMA50   : {result['ema50']}")
    print(f"  Message : {result['message']}\n")
