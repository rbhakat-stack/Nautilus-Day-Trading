
"""
RB NautilusTrader - 15-Minute Candle Builder

Construct completed regular-session 15-minute bars
from synthetic 5-minute OHLCV candles.

No broker connection. No order submission.
"""

from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data" / "synthetic_5m_candles.csv"
OUTPUT = ROOT / "data" / "synthetic_15m_candles.csv"


def build_15m_candles(df):
    df = df.copy()

    required = [
        "timestamp", "open", "high",
        "low", "close", "volume"
    ]

    if any(col not in df.columns for col in required):
        raise ValueError("Missing OHLCV columns")

    df["timestamp"] = pd.to_datetime(
        df["timestamp"], utc=True
    ).dt.tz_convert("America/New_York")

    if (
        df["timestamp"].isna().any()
        or df["timestamp"].duplicated().any()
        or not df["timestamp"].is_monotonic_increasing
    ):
        raise ValueError("Invalid candle timestamps")

    df = df.set_index("timestamp")

    results = []

    # Group by regular-session trading date.
    for session_date, session in df.groupby(
        df.index.date
    ):
        session_open = pd.Timestamp(
            session_date
        ).tz_localize(
            "America/New_York"
        ) + pd.Timedelta(hours=9, minutes=30)

        # One regular session: 26 completed 15m bars.
        for interval in range(26):
            bar_end = session_open + pd.Timedelta(
                minutes=15 * (interval + 1)
            )

            expected_times = [
                bar_end - pd.Timedelta(minutes=10),
                bar_end - pd.Timedelta(minutes=5),
                bar_end,
            ]

            # Include only these exact 3 completed
            # 5-minute candles.
            group = session.loc[
                session.index.isin(expected_times)
            ]

            if len(group) != 3:
                continue

            if list(group.index) != expected_times:
                continue

            results.append({
                "timestamp": bar_end.isoformat(),
                "open": group["open"].iloc[0],
                "high": group["high"].max(),
                "low": group["low"].min(),
                "close": group["close"].iloc[-1],
                "volume": group["volume"].sum(),
            })

    if not results:
        raise ValueError("No complete 15m candles")

    return pd.DataFrame(results)


def main():
    if not INPUT.exists():
        raise FileNotFoundError(INPUT)

    candles = pd.read_csv(INPUT)

    result = build_15m_candles(candles)

    OUTPUT.parent.mkdir(
        parents=True, exist_ok=True
    )

    result.to_csv(OUTPUT, index=False)

    print("RB 15-Minute Candle Builder")
    print("---------------------------")
    print("5m candles loaded:", len(candles))
    print("15m candles generated:", len(result))

    print()
    print("First 15m candle:")
    print(result.head(1).to_string(index=False))

    print()
    print("Last 15m candle:")
    print(result.tail(1).to_string(index=False))

    print()
    print("Saved file:", OUTPUT)


if __name__ == "__main__":
    main()
