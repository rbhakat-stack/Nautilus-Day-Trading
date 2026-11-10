
"""
RB NautilusTrader - Synthetic Market Data Generator

Generates one regular trading session of 5-minute
OHLCV candles for local development and testing.

No broker connection.
No real market data.
No order submission.
"""

import random
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd


ET = ZoneInfo("America/New_York")

START_PRICE = 100.00
NUMBER_OF_CANDLES = 78
SEED = 42


def generate_candles():
    rng = random.Random(SEED)

    session_start = datetime(
        2026, 11, 9, 9, 30, tzinfo=ET
    )

    candles = []
    previous_close = START_PRICE

    for i in range(NUMBER_OF_CANDLES):

        candle_end = session_start + timedelta(
            minutes=5 * (i + 1)
        )

        open_price = previous_close

        # Small simulated directional movement
        movement = rng.uniform(-0.35, 0.40)

        close_price = max(
            0.01,
            open_price + movement
        )

        upper_wick = rng.uniform(0.02, 0.18)
        lower_wick = rng.uniform(0.02, 0.18)

        high_price = (
            max(open_price, close_price) + upper_wick
        )

        low_price = max(
            0.01,
            min(open_price, close_price) - lower_wick
        )

        volume = rng.randint(10000, 50000)

        candles.append({
            "timestamp": candle_end.isoformat(),
            "open": round(open_price, 4),
            "high": round(high_price, 4),
            "low": round(low_price, 4),
            "close": round(close_price, 4),
            "volume": volume,
        })

        previous_close = close_price

    return pd.DataFrame(candles)


def main():
    df = generate_candles()

    # Project root is one directory above tools/
    project_root = Path(__file__).resolve().parents[1]

    # Generated datasets belong in data/, not tools/
    output_dir = project_root / "data"
    output_dir.mkdir(parents=True, exist_ok=True)

    output_file = output_dir / "synthetic_5m_candles.csv"

    # Save the generated candles
    df.to_csv(output_file, index=False)

    print("RB Synthetic Market Data Generator")
    print("----------------------------------")
    print("Candles generated:", len(df))
    print("First candle ends:", df.iloc[0]["timestamp"])
    print("Last candle ends:", df.iloc[-1]["timestamp"])

    print()
    print("First 5 candles:")
    print(df.head().to_string(index=False))

    print()
    print("Last 5 candles:")
    print(df.tail().to_string(index=False))

    print()
    print("Saved file:", output_file)


if __name__ == "__main__":
    main()
