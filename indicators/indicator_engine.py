
"""
RB NautilusTrader - Consolidated Indicator Engine

Phase 2: Calculate technical indicators from
completed synthetic five-minute OHLCV candles.

Development and testing only.
No broker connection or order submission.

Formulas are preliminary and require parity
validation before use in paper execution.
"""

from pathlib import Path
import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]

INPUT_FILE = (
    PROJECT_ROOT / "data" / "synthetic_5m_candles.csv"
)

OUTPUT_FILE = (
    PROJECT_ROOT / "data" / "indicators_5m.csv"
)


def wilder_average(values, period):
    """
    Wilder smoothing with initial simple average.

    Requires period valid observations.
    Earlier results remain NaN.
    """
    values = pd.Series(values, dtype=float)

    result = pd.Series(
        np.nan, index=values.index, dtype=float
    )

    valid = values.iloc[:period]

    if len(valid) < period or valid.isna().any():
        return result

    average = valid.mean()
    result.iloc[period - 1] = average

    for i in range(period, len(values)):
        value = values.iloc[i]

        if pd.isna(value):
            break

        average = (
            average * (period - 1) + value
        ) / period

        result.iloc[i] = average

    return result


def calculate_rsi(close, period=14):
    """
    RSI using Wilder smoothing.

    The first RSI needs 14 price changes,
    so it becomes available on bar 15.
    """
    delta = close.diff()

    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)

    # Exclude the first NaN change.
    average_gains = wilder_average(
        gains.iloc[1:].reset_index(drop=True),
        period
    )

    average_losses = wilder_average(
        losses.iloc[1:].reset_index(drop=True),
        period
    )

    rsi = pd.Series(
        np.nan, index=close.index, dtype=float
    )

    for i in range(period, len(close)):
        gain = average_gains.iloc[i - 1]
        loss = average_losses.iloc[i - 1]

        if pd.isna(gain) or pd.isna(loss):
            continue

        if gain == 0 and loss == 0:
            rsi.iloc[i] = 50.0
        elif loss == 0:
            rsi.iloc[i] = 100.0
        else:
            rs = gain / loss
            rsi.iloc[i] = 100 - 100 / (1 + rs)

    return rsi


def calculate_atr(df, period=14):
    """
    ATR using Wilder smoothing.

    Initial ATR is the mean of the first
    14 True Range observations.
    """
    previous_close = df["close"].shift(1)

    ranges = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - previous_close).abs(),
            (df["low"] - previous_close).abs(),
        ],
        axis=1,
    )

    true_range = ranges.max(axis=1)

    return wilder_average(true_range, period)


def calculate_indicators(df):
    """
    Calculate all six strategy indicators.
    """
    df = df.copy()

    required = [
        "timestamp", "open", "high",
        "low", "close", "volume"
    ]

    if any(column not in df for column in required):
        raise ValueError("Missing required OHLCV columns")

    df["timestamp"] = pd.to_datetime(
        df["timestamp"], utc=True
    ).dt.tz_convert("America/New_York")

    if df["timestamp"].isna().any():
        raise ValueError("Invalid timestamps")

    if (
        df["timestamp"].duplicated().any()
        or not df["timestamp"].is_monotonic_increasing
    ):
        raise ValueError("Timestamps must be unique and ordered")

    for column in required[1:]:
        df[column] = pd.to_numeric(
            df[column], errors="raise"
        )

        if not np.isfinite(df[column]).all():
            raise ValueError(f"Invalid {column} values")

    if (
        (df[["open", "high", "low", "close"]] <= 0)
        .any().any()
        or (df["volume"] <= 0).any()
        or (
            df["high"] <
            df[["open", "close", "low"]].max(axis=1)
        ).any()
        or (
            df["low"] >
            df[["open", "close", "high"]].min(axis=1)
        ).any()
    ):
        raise ValueError("Invalid OHLCV candle")

    # EMA: preliminary initialization.
    # Require the full period before displaying results.
    df["ema9"] = df["close"].ewm(
        span=9, adjust=False, min_periods=9
    ).mean()

    df["ema20"] = df["close"].ewm(
        span=20, adjust=False, min_periods=20
    ).mean()

    # VWAP: cumulative regular-session HLC3.
    typical_price = (
        df["high"] + df["low"] + df["close"]
    ) / 3

    session = df["timestamp"].dt.date

    cumulative_price_volume = (
        (typical_price * df["volume"])
        .groupby(session).cumsum()
    )

    cumulative_volume = (
        df["volume"].groupby(session).cumsum()
    )

    df["vwap"] = (
        cumulative_price_volume / cumulative_volume
    )

    # RSI(14): Wilder smoothing
    df["rsi14"] = calculate_rsi(df["close"])

    # RVOL(20): current volume divided by the
    # inclusive 20-bar average.
    # This is a preliminary RB-style definition.
    average_volume = df["volume"].rolling(
        window=20, min_periods=20
    ).mean()

    df["rvol20"] = (
        df["volume"] / average_volume
    )

    # ATR(14): Wilder smoothing
    df["atr14"] = calculate_atr(df)

    indicator_columns = [
        "ema9", "ema20", "vwap",
        "rsi14", "rvol20", "atr14"
    ]

    df["indicators_ready"] = (
        df[indicator_columns].notna().all(axis=1)
    )

    return df


def main():
    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            f"Market data not found: {INPUT_FILE}"
        )

    candles = pd.read_csv(INPUT_FILE)

    result = calculate_indicators(candles)

    OUTPUT_FILE.parent.mkdir(
        parents=True, exist_ok=True
    )

    result.to_csv(OUTPUT_FILE, index=False)

    print("RB Consolidated Indicator Engine")
    print("--------------------------------")
    print("Candles processed:", len(result))
    print(
        "Candles with all indicators ready:",
        int(result["indicators_ready"].sum())
    )

    print()
    print("Latest completed candle:")

    last = result.iloc[-1]

    for column in [
        "timestamp", "close", "ema9",
        "ema20", "vwap", "rsi14",
        "rvol20", "atr14"
    ]:
        value = last[column]

        if isinstance(value, (int, float, np.number)):
            print(f"{column}: {value:.4f}")
        else:
            print(f"{column}: {value}")

    print()
    print(
        "Latest indicators ready:",
        bool(last["indicators_ready"])
    )
    print("Saved file:", OUTPUT_FILE)


if __name__ == "__main__":
    main()
