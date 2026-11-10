
"""
RB NautilusTrader - Signal Engine
Phase 1: Synthetic signal evaluation with candle timing.

No broker connection or order submission.
"""

from datetime import datetime
from math import isfinite
from zoneinfo import ZoneInfo

from strategy.candle_timing import latest_completed_15m


ET = ZoneInfo("America/New_York")

LONG_RULES = {
    "rsi_min": 55,
    "rvol_min": 1.5,
}

SHORT_RULES = {
    "rsi_max": 45,
    "rvol_min": 1.5,
}


def validate_candle_timing(data):
    """
    Verify that the supplied 15-minute bar has the
    latest eligible completed 15-minute end timestamp.

    Both timestamps must be timezone-aware.

    This does not yet verify actual market-data arrival.
    """

    signal_time = data.get("signal_time")
    bar_15m_end = data.get("bar_15m_end")

    if not isinstance(signal_time, datetime):
        return False

    if not isinstance(bar_15m_end, datetime):
        return False

    if signal_time.tzinfo is None:
        return False

    if bar_15m_end.tzinfo is None:
        return False

    try:
        expected_end = latest_completed_15m(signal_time)

        if expected_end is None:
            return False

        actual_end = bar_15m_end.astimezone(ET)

        return actual_end == expected_end

    except (ValueError, TypeError, OverflowError):
        return False


def evaluate_signal(data):
    """
    Evaluate LONG and SHORT technical conditions.

    Returns:
        LONG
        SHORT
        NO SIGNAL
        NO SIGNAL - MISSING DATA
        NO SIGNAL - INVALID DATA
        NO SIGNAL - INVALID CANDLE TIMING

    Uses supplied synthetic indicator values.
    Does not place orders.
    """

    required = [
        "close",
        "open",
        "vwap",
        "ema9",
        "ema20",
        "rsi",
        "rvol",
        "close_15m",
        "ema20_15m",
        "signal_time",
        "bar_15m_end",
    ]

    if not isinstance(data, dict):
        return "NO SIGNAL - INVALID DATA"

    if any(key not in data for key in required):
        return "NO SIGNAL - MISSING DATA"

    # Reject missing, nonnumeric and nonfinite indicators.
    numeric_fields = [
        "close",
        "open",
        "vwap",
        "ema9",
        "ema20",
        "rsi",
        "rvol",
        "close_15m",
        "ema20_15m",
    ]

    for field in numeric_fields:
        value = data[field]

        if isinstance(value, bool):
            return "NO SIGNAL - INVALID DATA"

        try:
            numeric_value = float(value)
        except (ValueError, TypeError, OverflowError):
            return "NO SIGNAL - INVALID DATA"

        if not isfinite(numeric_value):
            return "NO SIGNAL - INVALID DATA"

    # Reject invalid indicator ranges and prices.
    if (
        data["close"] <= 0
        or data["open"] <= 0
        or data["vwap"] <= 0
        or data["ema9"] <= 0
        or data["ema20"] <= 0
        or data["close_15m"] <= 0
        or data["ema20_15m"] <= 0
        or not 0 <= data["rsi"] <= 100
        or data["rvol"] < 0
    ):
        return "NO SIGNAL - INVALID DATA"

    # Confirm correct completed 15-minute candle.
    if not validate_candle_timing(data):
        return "NO SIGNAL - INVALID CANDLE TIMING"

    # LONG conditions: all must pass.
    long_signal = (
        data["close"] > data["vwap"]
        and data["ema9"] > data["ema20"]
        and data["rsi"] > LONG_RULES["rsi_min"]
        and data["rvol"] > LONG_RULES["rvol_min"]
        and data["close"] > data["open"]
        and data["close_15m"] > data["ema20_15m"]
    )

    # SHORT conditions: all must pass.
    short_signal = (
        data["close"] < data["vwap"]
        and data["ema9"] < data["ema20"]
        and data["rsi"] < SHORT_RULES["rsi_max"]
        and data["rvol"] > SHORT_RULES["rvol_min"]
        and data["close"] < data["open"]
        and data["close_15m"] < data["ema20_15m"]
    )

    if long_signal:
        return "LONG"

    if short_signal:
        return "SHORT"

    return "NO SIGNAL"


if __name__ == "__main__":

    # Synthetic example: not live market data.
    # Five-minute signal bar ends at 9:50 AM ET.
    # Latest completed 15-minute bar ends at 9:45 AM ET.

    test_data = {
        "close": 105.0,
        "open": 104.0,
        "vwap": 103.0,
        "ema9": 104.5,
        "ema20": 103.5,
        "rsi": 62.0,
        "rvol": 1.8,
        "close_15m": 105.0,
        "ema20_15m": 103.8,

        "signal_time": datetime(
            2026, 11, 9, 9, 50,
            tzinfo=ET
        ),

        "bar_15m_end": datetime(
            2026, 11, 9, 9, 45,
            tzinfo=ET
        ),
    }

    result = evaluate_signal(test_data)

    print("RB NautilusTrader Signal Engine")
    print("Signal:", result)
    print(
        "15-minute candle timing valid:",
        validate_candle_timing(test_data)
    )
