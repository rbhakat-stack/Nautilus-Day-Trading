"""RB v1.1-equivalent trade PLAN math for an independent NautilusTrader project.

Source: RB_V11_FORMULA_PARITY_SPEC.md, audited origin/main c3bbca4.
This module does NOT decide eligibility, score, generate signals or submit orders.
No reliance on IBKR/TrendSpider/Alpaca. Python standard library only.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
from math import isfinite
from typing import Any, Mapping

MIN_BUFFER = Decimal("0.01")
BUFFER_PCT = Decimal("0.0002")
RISK_PCT = Decimal("0.0025")
INVESTMENT_CAP = Decimal("20000")
DEFAULT_EQUITY = Decimal("100000")
EPSILON_TICKS = Decimal("0.0000001")


def d(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("Boolean is not a numeric price")
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise ValueError(f"Invalid numeric value: {value!r}") from exc
    if not result.is_finite():
        raise ValueError("Nonfinite number")
    return result


def clean8(value: Any) -> Decimal:
    return d(value).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)


def tick_for(price: Any) -> Decimal:
    return Decimal("0.01") if abs(d(price)) >= 1 else Decimal("0.0001")


def round_to_tick(value: Any, mode: str, tick: Any) -> Decimal:
    """RB rounding: epsilon is in *tick units*, not dollars."""
    tick = d(tick)
    if tick <= 0:
        raise ValueError("Tick must be positive")
    ticks = d(value) / tick
    if mode == "up":
        n = (ticks - EPSILON_TICKS).to_integral_value(rounding=ROUND_CEILING)
    elif mode == "down":
        n = (ticks + EPSILON_TICKS).to_integral_value(rounding=ROUND_FLOOR)
    elif mode == "nearest":
        n = (ticks + EPSILON_TICKS).to_integral_value(rounding=ROUND_HALF_UP)
    else:
        raise ValueError("Unsupported rounding mode")
    return n * tick


def floor_shares(value: Any) -> int:
    try:
        x = clean8(value)
    except ValueError:
        return 0
    return max(0, int(x.to_integral_value(rounding=ROUND_FLOOR))) if x > 0 else 0


def entry_trigger(side: str, high: Any, low: Any) -> dict[str, Decimal]:
    """Audited dynamic-buffer stop entry, no order is placed."""
    if side not in ("LONG", "SHORT"):
        raise ValueError("side must be LONG or SHORT")
    signal = d(high if side == "LONG" else low)
    if signal <= 0:
        raise ValueError("Signal price must be >0")
    tick = tick_for(signal)
    raw = max(MIN_BUFFER, signal * BUFFER_PCT)
    buffer = max(MIN_BUFFER, round_to_tick(raw, "nearest", tick))
    preliminary = signal + buffer if side == "LONG" else signal - buffer
    # roundPrice uses the tick of the computed price, not necessarily signal.
    entry = round_to_tick(preliminary, "nearest", tick_for(preliminary))
    return {"signalPrice": signal, "bufferRaw": raw,
            "buffer": buffer, "entry": entry}


def build_plan(side: str, high: Any, low: Any, atr: Any, *,
               equity: Any = DEFAULT_EQUITY,
               investment_amount: Any = INVESTMENT_CAP,
               entry_override: Any = None) -> dict[str, Any]:
    """Pure construction math. NOT a tradability/portfolio approval.

    entry_override allows exact A_TARGET fixture replication (entryMethod in
    the original buildPlan is TRIGGER); normal callers should omit it.
    """
    hi, lo, a = d(high), d(low), d(atr)
    eq, investment = d(equity), d(investment_amount)
    if not (hi >= lo > 0 and a > 0 and eq > 0 and investment >= 0):
        raise ValueError("Invalid candle, ATR, equity or investment amount")
    if entry_override is None:
        trigger = entry_trigger(side, hi, lo)
        entry = trigger["entry"]
        raw_buffer = trigger["bufferRaw"]
        buffer = trigger["buffer"]
        signal = trigger["signalPrice"]
    else:
        if side not in ("LONG", "SHORT"):
            raise ValueError("Invalid side")
        entry = d(entry_override)
        signal = hi if side == "LONG" else lo
        raw_buffer = Decimal(0)
        buffer = Decimal(0)
    if entry <= 0:
        raise ValueError("Invalid entry")
    structural = clean8(entry - lo if side == "LONG" else hi - entry)
    atr_risk = clean8(a)
    if structural <= 0:
        raise ValueError("Invalid structural risk")
    r_raw = max(structural, atr_risk)
    risk_method = "STRUCTURAL" if structural >= atr_risk else "ATR"
    tick = tick_for(entry)
    R = round_to_tick(r_raw, "up", tick)
    stop_raw = entry - R if side == "LONG" else entry + R
    target_raw = entry + 2 * R if side == "LONG" else entry - 2 * R
    stop = round_to_tick(stop_raw, "nearest", tick_for(stop_raw))
    target = round_to_tick(target_raw, "nearest", tick_for(target_raw))
    risk_budget = clean8(eq * RISK_PCT)
    risk_shares = floor_shares(risk_budget / R)
    investment_shares = floor_shares(investment / entry)
    shares = min(risk_shares, investment_shares)
    limited_by = ("BOTH" if risk_shares == investment_shares else
                  "RISK" if risk_shares < investment_shares else "INVESTMENT")
    valid = (stop < entry < target if side == "LONG" else target < entry < stop)
    valid = valid and target > 0
    return {
        "direction": side, "orderType": "BUY STOP" if side == "LONG" else "SELL STOP",
        "signalPrice": signal, "bufferRaw": raw_buffer, "buffer": buffer,
        "entry": entry, "structuralRisk": structural, "atrRisk": atr_risk,
        "rRaw": r_raw, "riskPerShare": R, "riskMethod": risk_method,
        "stop": stop, "target": target, "rewardRatio": Decimal(2),
        "maxDollarRisk": risk_budget, "riskShares": risk_shares,
        "investmentShares": investment_shares, "shares": shares,
        "limitedBy": limited_by, "positionValue": clean8(shares * entry),
        "maxLoss": clean8(shares * R),
        "potentialProfit": clean8(shares * abs(target - entry)),
        "structureValid": valid,
        "status": "PREVIEW ONLY - NOT AUTHORIZED",
    }


def construct_trade(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """Adapter for existing data/signal_results.csv rows. Preview only."""
    side = row.get("signal_result")
    if side not in ("LONG", "SHORT"):
        return None
    return build_plan(side, row["high"], row["low"], row["atr14"])


def main() -> None:
    import csv
    from pathlib import Path
    source = Path(__file__).resolve().parents[1] / "data" / "signal_results.csv"
    if not source.exists():
        raise SystemExit(f"Missing CSV: {source}")
    with source.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    signals = [r for r in rows if r.get("signal_result") in ("LONG", "SHORT")]
    print(f"Technical candidates: {len(signals)}; ALL PLANS PREVIEW-ONLY")
    for row in signals:
        print(f"\n{row.get('timestamp')}: {row['signal_result']}")
        for key, value in construct_trade(row).items():
            print(f"{key}: {value}")
    print("\nNo orders submitted. No eligibility/score asserted.")


if __name__ == "__main__":
    main()
