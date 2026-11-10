
import pandas as pd

# Synthetic 5-minute candles
data = {
    "high": [
        101, 102, 103, 102, 104,
        105, 104, 106, 107, 108,
        107, 109, 110, 109, 111,
        112, 111, 113, 114, 115
    ],
    "low": [
        99, 100, 101, 100, 102,
        103, 102, 104, 105, 106,
        105, 107, 108, 107, 109,
        110, 109, 111, 112, 113
    ],
    "close": [
        100, 101, 102, 101, 103,
        104, 103, 105, 106, 107,
        106, 108, 109, 108, 110,
        111, 110, 112, 113, 114
    ]
}

df = pd.DataFrame(data)

period = 14

# Previous candle closing price
previous_close = df["close"].shift(1)

# Calculate True Range
tr_components = pd.concat([
    df["high"] - df["low"],
    (df["high"] - previous_close).abs(),
    (df["low"] - previous_close).abs()
], axis=1)

df["true_range"] = tr_components.max(axis=1)

# Initialize ATR with first 14 True Range values
initial_atr = df["true_range"].iloc[:period].mean()

# Wilder smoothing
atr = initial_atr

for i in range(period, len(df)):
    atr = (
        atr * (period - 1)
        + df["true_range"].iloc[i]
    ) / period

print("Latest closing price:", df["close"].iloc[-1])
print("ATR(14):", round(atr, 4))

# Illustrative LONG trade construction
entry_price = df["high"].iloc[-1] + 0.02

stop_loss = entry_price - atr
take_profit = entry_price + (2 * atr)

risk_per_share = entry_price - stop_loss
max_risk = 250

quantity = int(max_risk / risk_per_share)

print()
print("Example LONG Trade")
print("Entry:", round(entry_price, 4))
print("Stop Loss:", round(stop_loss, 4))
print("Take Profit:", round(take_profit, 4))
print("Quantity (risk-only):", quantity)
print("Planned Risk:", round(quantity * risk_per_share, 2))
