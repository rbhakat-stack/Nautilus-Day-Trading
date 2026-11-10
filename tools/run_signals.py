
"""
RB NautilusTrader - Multi-Timeframe Signal Integration

Phase 2: Evaluate completed synthetic five-minute
candles using the latest completed fifteen-minute
trend confirmation.

No broker connection.
No order submission.
No live trading.
"""

from pathlib import Path
from datetime import time

import pandas as pd

from strategy.signal_engine import evaluate_signal
from strategy.candle_timing import latest_completed_15m


ROOT = Path(__file__).resolve().parents[1]

INPUT_5M = ROOT / "data" / "indicators_5m.csv"
INPUT_15M = ROOT / "data" / "indicators_15m.csv"

OUTPUT = ROOT / "data" / "signal_results.csv"

ENTRY_CUTOFF = time(15, 30)


def load_candles(path):
    if not path.exists():
        raise FileNotFoundError(path)

    df = pd.read_csv(path)

    df["timestamp"] = pd.to_datetime(
        df["timestamp"], utc=True
    ).dt.tz_convert("America/New_York")

    if (
        df["timestamp"].isna().any()
        or df["timestamp"].duplicated().any()
        or not df["timestamp"].is_monotonic_increasing
    ):
        raise ValueError(
            f"Invalid candle timestamps in {path}"
        )

    return df


def main():
    five = load_candles(INPUT_5M)
    fifteen = load_candles(INPUT_15M)

    # Rename 15-minute data to distinguish it
    # from five-minute indicator values.
    fifteen = fifteen.rename(
        columns={
            "timestamp": "bar_15m_end",
            "close": "close_15m",
        }
    )

    # Keep only the fields needed for confirmation.
    fifteen = fifteen[
        ["bar_15m_end", "close_15m",
         "ema20_15m", "ema20_ready"]
    ]

    # Backward-only join:
    # Never take a 15m candle ending after
    # the five-minute signal timestamp.
    combined = pd.merge_asof(
        five.sort_values("timestamp"),
        fifteen.sort_values("bar_15m_end"),
        left_on="timestamp",
        right_on="bar_15m_end",
        direction="backward",
        allow_exact_matches=True,
    )

    results = []

    for _, row in combined.iterrows():
        signal_time = row["timestamp"]

        # Use only candles whose indicators
        # have completed their initial warm-up.
        if not bool(row["indicators_ready"]):
            result = "NO SIGNAL - 5M NOT READY"

        elif pd.isna(row["bar_15m_end"]):
            result = "NO SIGNAL - 15M NOT READY"

        elif not bool(row["ema20_ready"]):
            result = "NO SIGNAL - 15M NOT READY"

        elif signal_time.time() > ENTRY_CUTOFF:
            result = "NO SIGNAL - OUTSIDE ENTRY WINDOW"

        else:
            expected_end = latest_completed_15m(
                signal_time.to_pydatetime()
            )

            actual_end = row[
                "bar_15m_end"
            ].to_pydatetime()

            # Reject if no exact eligible
            # completed 15-minute candle exists.
            if (
                expected_end is None
                or actual_end != expected_end
            ):
                result = (
                    "NO SIGNAL - INVALID CANDLE TIMING"
                )

            else:
                data = {
                    "open": row["open"],
                    "close": row["close"],
                    "vwap": row["vwap"],
                    "ema9": row["ema9"],
                    "ema20": row["ema20"],
                    "rsi": row["rsi14"],
                    "rvol": row["rvol20"],
                    "close_15m": row["close_15m"],
                    "ema20_15m": row["ema20_15m"],
                    "signal_time": (
                        signal_time.to_pydatetime()
                    ),
                    "bar_15m_end": actual_end,
                }

                result = evaluate_signal(data)

        results.append(result)

    combined["signal_result"] = results

    OUTPUT.parent.mkdir(
        parents=True, exist_ok=True
    )

    combined.to_csv(OUTPUT, index=False)

    print("RB Multi-Timeframe Signal Engine")
    print("--------------------------------")
    print("5m candles:", len(five))
    print("15m candles:", len(fifteen))

    print()
    print("Signal evaluation summary:")
    print(
        combined["signal_result"]
        .value_counts()
        .to_string()
    )

    print()
    print("Last 10 decisions:")
    print(
        combined[
            ["timestamp", "close", "rsi14",
             "rvol20", "signal_result"]
        ].tail(10).to_string(index=False)
    )

    print()
    print("Saved file:", OUTPUT)


if __name__ == "__main__":
    main()
