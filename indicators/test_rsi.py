
import pandas as pd

# Synthetic 5-minute closing prices
prices = pd.Series([
    100, 101, 102, 101, 103,
    104, 103, 105, 106, 107,
    106, 108, 109, 108, 110,
    111, 110, 112, 113, 114,
    113, 115, 116, 115, 117,
], dtype=float)

period = 14

# Calculate price changes
delta = prices.diff()

gains = delta.clip(lower=0)
losses = -delta.clip(upper=0)

# Initialize Wilder averages using first 14 changes
avg_gain = gains.iloc[1:period + 1].mean()
avg_loss = losses.iloc[1:period + 1].mean()

# Apply Wilder smoothing to subsequent changes
for i in range(period + 1, len(prices)):
    avg_gain = (
        avg_gain * (period - 1) + gains.iloc[i]
    ) / period

    avg_loss = (
        avg_loss * (period - 1) + losses.iloc[i]
    ) / period

# Convert averages into RSI
if avg_loss == 0:
    rsi = 100.0 if avg_gain > 0 else 50.0
else:
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

print("Latest closing price:", prices.iloc[-1])
print("RSI(14):", round(rsi, 4))

if rsi > 55:
    print("RESULT: LONG RSI condition passed")
elif rsi < 45:
    print("RESULT: SHORT RSI condition passed")
else:
    print("RESULT: Neither RSI condition passed")
