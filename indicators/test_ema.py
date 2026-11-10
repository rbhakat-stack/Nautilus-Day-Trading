
import pandas as pd

# Synthetic closing prices for testing only
prices = pd.Series([
    100, 101, 102, 101, 103,
    104, 103, 105, 106, 107,
    106, 108, 109, 108, 110,
    111, 110, 112, 113, 114,
    113, 115, 116, 115, 117,
])

# Calculate exponential moving averages
ema9 = prices.ewm(span=9, adjust=False).mean()
ema20 = prices.ewm(span=20, adjust=False).mean()

print("Latest closing price:", prices.iloc[-1])
print("EMA9:", round(ema9.iloc[-1], 4))
print("EMA20:", round(ema20.iloc[-1], 4))

if ema9.iloc[-1] > ema20.iloc[-1]:
    print("RESULT: Bullish EMA alignment")
else:
    print("RESULT: Bearish or neutral EMA alignment")
