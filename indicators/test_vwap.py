
import pandas as pd

# Synthetic 5-minute candles for testing
data = {
    "high": [101, 102, 103, 104, 105],
    "low": [99, 100, 101, 102, 103],
    "close": [100, 101, 102, 103, 104],
    "volume": [1000, 1500, 2000, 1200, 1800],
}

df = pd.DataFrame(data)

# Typical price (HLC3)
df["typical_price"] = (
    df["high"] + df["low"] + df["close"]
) / 3

# Cumulative volume-weighted price
df["price_volume"] = (
    df["typical_price"] * df["volume"]
)

df["vwap"] = (
    df["price_volume"].cumsum()
    / df["volume"].cumsum()
)

latest_close = df["close"].iloc[-1]
latest_vwap = df["vwap"].iloc[-1]

print("Latest closing price:", latest_close)
print("VWAP:", round(latest_vwap, 4))

if latest_close > latest_vwap:
    print("RESULT: Price above VWAP - Bullish")
elif latest_close < latest_vwap:
    print("RESULT: Price below VWAP - Bearish")
else:
    print("RESULT: Price equals VWAP - Neutral")
