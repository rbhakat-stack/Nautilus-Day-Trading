
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

SESSION_OPEN = time(9, 30)
SESSION_CLOSE = time(16, 0)


def latest_completed_15m(signal_time):
    """
    Given the end time of a completed 5-minute candle,
    return the end time of the latest completed
    regular-session 15-minute candle.

    Returns None if none exists yet.

    Assumes bars ending at signal_time are finalized
    and available before evaluation.
    """
    if signal_time.tzinfo is None:
        raise ValueError("Timezone-aware timestamp required")

    signal_time = signal_time.astimezone(ET)

    session_start = signal_time.replace(
        hour=9, minute=30, second=0, microsecond=0
    )

    session_end = signal_time.replace(
        hour=16, minute=0, second=0, microsecond=0
    )

    if not (session_start <= signal_time <= session_end):
        return None

    elapsed_minutes = int(
        (signal_time - session_start).total_seconds() // 60
    )

    completed_intervals = elapsed_minutes // 15

    if completed_intervals == 0:
        return None

    return session_start + timedelta(
        minutes=completed_intervals * 15
    )


if __name__ == "__main__":
    test_times = ["09:35", "09:40", "09:45",
                  "09:50", "09:55", "10:00"]

    for t in test_times:
        hour, minute = map(int, t.split(":"))
        signal_time = datetime(
            2026, 11, 9, hour, minute, tzinfo=ET
        )

        completed = latest_completed_15m(signal_time)

        result = (
            completed.strftime("%H:%M")
            if completed is not None else "NONE"
        )

        print(f"Signal {t} -> Completed 15m: {result}")
