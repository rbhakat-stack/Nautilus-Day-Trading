
import pandas as pd

# Synthetic volumes for 25 completed five-minute candles
volumes = pd.Series([
    1000, 1100, 950, 1050, 1200,
    1000, 1150, 900, 1100, 1050,
    1000, 1200, 950, 1100, 1000,
    1150, 1050, 950, 1100, 1000,
    1200, 1100, 1050, 1000, 2000,
], dtype=float)

period = 20
threshold = 1.5

# Average of the previous 20 completed candles
# Excludes the current candle from the denominator.
average_volume = volumes.shift(1).rolling(
    window=period,
    min_periods=period
).mean()

latest_volume = volumes.iloc[-1]
latest_average = average_volume.iloc[-1]

rvol = latest_volume / latest_average

print("Current 5-minute volume:", int(latest_volume))
print("Previous 20-bar average volume:", round(latest_average, 2))
print("RVOL(20):", round(rvol, 4))

if rvol > threshold:
    print("RESULT: RVOL condition passed")
else:
    print("RESULT: RVOL condition failed")
