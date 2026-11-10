
"""
RB NautilusTrader - Signal Engine Tests

Synthetic data only.
No broker connection or order submission.
"""

import sys
from copy import deepcopy
from datetime import datetime, timedelta
from math import nan, inf
from pathlib import Path
from zoneinfo import ZoneInfo

# Make project imports available
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from strategy.signal_engine import evaluate_signal


ET = ZoneInfo("America/New_York")

SIGNAL_TIME = datetime(2026, 11, 9, 9, 50, tzinfo=ET)
BAR_15M_END = datetime(2026, 11, 9, 9, 45, tzinfo=ET)


LONG_DATA = {
    "close": 105.0,
    "open": 104.0,
    "vwap": 103.0,
    "ema9": 104.5,
    "ema20": 103.5,
    "rsi": 62.0,
    "rvol": 1.8,
    "close_15m": 105.0,
    "ema20_15m": 103.8,
    "signal_time": SIGNAL_TIME,
    "bar_15m_end": BAR_15M_END,
}

SHORT_DATA = {
    "close": 95.0,
    "open": 96.0,
    "vwap": 97.0,
    "ema9": 95.5,
    "ema20": 96.5,
    "rsi": 38.0,
    "rvol": 1.8,
    "close_15m": 95.0,
    "ema20_15m": 96.2,
    "signal_time": SIGNAL_TIME,
    "bar_15m_end": BAR_15M_END,
}


def modified(base, **changes):
    data = deepcopy(base)
    data.update(changes)
    return data


tests = [
    # Original signal tests
    ("Valid LONG", LONG_DATA, "LONG"),
    ("Valid SHORT", SHORT_DATA, "SHORT"),
    (
        "Neutral RSI",
        modified(LONG_DATA, rsi=50.0),
        "NO SIGNAL",
    ),
    (
        "Low RVOL",
        modified(LONG_DATA, rvol=1.2),
        "NO SIGNAL",
    ),
    (
        "Missing VWAP",
        {k: v for k, v in LONG_DATA.items() if k != "vwap"},
        "NO SIGNAL - MISSING DATA",
    ),

    # Threshold boundaries
    (
        "LONG RSI exactly 55",
        modified(LONG_DATA, rsi=55.0),
        "NO SIGNAL",
    ),
    (
        "SHORT RSI exactly 45",
        modified(SHORT_DATA, rsi=45.0),
        "NO SIGNAL",
    ),
    (
        "RVOL exactly 1.5",
        modified(LONG_DATA, rvol=1.5),
        "NO SIGNAL",
    ),
    (
        "Price equals VWAP",
        modified(LONG_DATA, vwap=105.0),
        "NO SIGNAL",
    ),
    (
        "EMA9 equals EMA20",
        modified(LONG_DATA, ema9=103.5),
        "NO SIGNAL",
    ),
    (
        "15-minute values equal",
        modified(LONG_DATA, close_15m=103.8),
        "NO SIGNAL",
    ),

    # Candle timing tests
    (
        "Wrong 15m candle",
        modified(
            LONG_DATA,
            bar_15m_end=BAR_15M_END + timedelta(minutes=15),
        ),
        "NO SIGNAL - INVALID CANDLE TIMING",
    ),
    (
        "Stale 15m candle",
        modified(
            LONG_DATA,
            bar_15m_end=BAR_15M_END - timedelta(minutes=15),
        ),
        "NO SIGNAL - INVALID CANDLE TIMING",
    ),
    (
        "No completed 15m candle at 09:35",
        modified(
            LONG_DATA,
            signal_time=datetime(
                2026, 11, 9, 9, 35, tzinfo=ET
            ),
        ),
        "NO SIGNAL - INVALID CANDLE TIMING",
    ),
    (
        "Missing signal timestamp",
        {
            k: v for k, v in LONG_DATA.items()
            if k != "signal_time"
        },
        "NO SIGNAL - MISSING DATA",
    ),
    (
        "Naive timestamp",
        modified(
            LONG_DATA,
            signal_time=datetime(2026, 11, 9, 9, 50),
        ),
        "NO SIGNAL - INVALID CANDLE TIMING",
    ),

    # Invalid numeric data
    (
        "NaN RSI",
        modified(LONG_DATA, rsi=nan),
        "NO SIGNAL - INVALID DATA",
    ),
    (
        "Infinite RVOL",
        modified(LONG_DATA, rvol=inf),
        "NO SIGNAL - INVALID DATA",
    ),
    (
        "Negative closing price",
        modified(LONG_DATA, close=-105.0),
        "NO SIGNAL - INVALID DATA",
    ),
    (
        "RSI above 100",
        modified(LONG_DATA, rsi=110.0),
        "NO SIGNAL - INVALID DATA",
    ),
]


failures = 0

for number, (name, data, expected) in enumerate(tests, start=1):
    try:
        actual = evaluate_signal(data)
    except Exception as exc:
        actual = f"EXCEPTION: {type(exc).__name__}: {exc}"

    if actual == expected:
        print(f"PASS {number:02d}: {name}")
    else:
        failures += 1
        print(
            f"FAIL {number:02d}: {name}\n"
            f"  Expected: {expected}\n"
            f"  Actual:   {actual}"
        )


print()
print(
    f"RESULTS: {len(tests) - failures}/{len(tests)} tests passed"
)

if failures:
    sys.exit(1)
