"""
Regime Check
=============
Fetches Nifty50 daily data and checks if price is above EMA50.

Returns:
    dict with keys:
        - regime: 'GO' or 'PAUSE'
        - nifty_price: float
        - ema50: float
        - message: str
"""

import yfinance as yf
import pandas as pd


def check_regime():
    try:
        ticker = yf.Ticker("^NSEI")
        df = ticker.history(period="3mo", interval="1d")

        if df.empty or len(df) < 52:
            return {
                "regime": "PAUSE",
                "nifty_price": None,
                "ema50": None,
                "message": "Could not fetch Nifty data — defaulting to PAUSE"
            }

        close = df["Close"]
        ema50 = round(float(close.ewm(span=50, adjust=False).mean().iloc[-1]), 2)
        price = round(float(close.iloc[-1]), 2)
        prev  = round(float(close.iloc[-2]), 2)
        change = round((price - prev) / prev * 100, 2)

        if price > ema50:
            regime  = "GO"
            message = f"Nifty {price} > EMA50 {ema50} — Market healthy, entries allowed"
        else:
            regime  = "PAUSE"
            message = f"Nifty {price} < EMA50 {ema50} — Market weak, no new entries today"

        return {
            "regime":       regime,
            "nifty_price":  price,
            "nifty_change": change,
            "ema50":        ema50,
            "message":      message
        }

    except Exception as e:
        return {
            "regime":      "PAUSE",
            "nifty_price": None,
            "ema50":       None,
            "message":     f"Regime check failed: {str(e)} — defaulting to PAUSE"
        }


if __name__ == "__main__":
    result = check_regime()
    print(f"\nRegime Check")
    print(f"  Status  : {result['regime']}")
    print(f"  Nifty   : {result['nifty_price']} ({result.get('nifty_change', 'N/A')}%)")
    print(f"  EMA50   : {result['ema50']}")
    print(f"  Message : {result['message']}\n")
