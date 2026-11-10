
"""
RB NautilusTrader - 15-Minute EMA20

Calculates EMA20 from completed 15-minute
candles generated from synthetic market data.

Development/testing only.
No broker connection or order submission.
"""

from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]

INPUT_FILE = (
    ROOT / "data" / "synthetic_15m_candles.csv"
)

OUTPUT_FILE = (
    ROOT / "data" / "indicators_15m.csv"
)


def calculate_15m_ema(df):
    df = df.copy()

    df["timestamp"] = pd.to_datetime(
        df["timestamp"],
        utc=True
    ).dt.tz_convert("America/New_York")

    if (
        df["timestamp"].isna().any()
        or df["timestamp"].duplicated().any()
        or not df["timestamp"].is_monotonic_increasing
    ):
        raise ValueError("Invalid 15-minute timestamps")

    df["ema20_15m"] = df["close"].ewm(
        span=20,
        adjust=False,
        min_periods=20
    ).mean()

    df["ema20_ready"] = df["ema20_15m"].notna()

    return df


def main():

    if not INPUT_FILE.exists():
        raise FileNotFoundError(INPUT_FILE)

    candles = pd.read_csv(INPUT_FILE)

    result = calculate_15m_ema(candles)

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    result.to_csv(OUTPUT_FILE, index=False)

    print("RB 15-Minute EMA20 Engine")
    print("-------------------------")

    print("15-minute candles:", len(result))

    print(
        "Candles with EMA20 ready:",
        int(result["ema20_ready"].sum())
    )

    print()
    print("Latest completed 15-minute candle:")

    latest = result.iloc[-1]

    print("Timestamp:", latest["timestamp"])
    print("Close:", round(latest["close"], 4))
    print(
        "EMA20:",
        round(latest["ema20_15m"], 4)
    )

    if latest["close"] > latest["ema20_15m"]:
        print("Trend: BULLISH")
    elif latest["close"] < latest["ema20_15m"]:
        print("Trend: BEARISH")
    else:
        print("Trend: NEUTRAL")

    print()
    print("Saved file:", OUTPUT_FILE)


if __name__ == "__main__":
    main()
