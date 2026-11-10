"""RB v1.1 golden-fixture comparisons. Run from project root.

Never silently substitute calculated expected values. Fixtures are external
read-only audit references from audited production commit c3bbca4.
"""
import json
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from risk.trade_constructor import (
    build_plan, entry_trigger, round_to_tick, floor_shares, tick_for,
)

FIXTURES = ROOT / "reference" / "RB_v1.1_parity" / "RB_V11_GOLDEN_FIXTURES.json"
CHECK_FIELDS = (
    "signalPrice", "buffer", "entry", "structuralRisk", "atrRisk",
    "rRaw", "riskPerShare", "riskMethod", "stop", "target", "rewardRatio",
    "maxDollarRisk", "riskShares", "investmentShares", "shares",
    "limitedBy", "positionValue", "maxLoss", "potentialProfit", "orderType",
)


def equivalent(actual, expected):
    if isinstance(actual, Decimal):
        # Numeric comparison is exact at fixture's published decimal precision.
        return abs(actual - Decimal(str(expected))) <= Decimal("0.000000000001") if expected is not None else False
    return actual == expected


def main():
    if not FIXTURES.exists():
        raise SystemExit(f"Golden fixture file missing: {FIXTURES}")
    with FIXTURES.open(encoding="utf-8") as fh:
        fixtures = json.load(fh)["fixtures"]
    tested = failed = 0
    for case in fixtures:
        group = case["group"]
        id_ = case["id"]
        inp, expected = case["inputs"], case["output"]
        results = []
        if group == "A_TRADE_CONSTRUCTION" and expected.get("plan") is not None:
            plan = build_plan(inp["direction"], inp["high"], inp["low"],
                              inp["atr"], equity=inp.get("accountEquity",100000),
                              investment_amount=inp.get("investmentAmount",20000))
            results = [(f, plan[f], expected["plan"][f]) for f in CHECK_FIELDS
                       if f in expected["plan"]]
        elif group == "A_BUFFER":
            trig = entry_trigger("LONG", inp["high"], inp["low"])
            results = [("bufferRaw",trig["bufferRaw"], expected["buffer"]["raw"]),
                       ("buffer",trig["buffer"],expected["buffer"]["rounded"]),
                       ("entry",trig["entry"],expected["trigger"]["entry"]),
                       ("tick",tick_for(inp["high"]),expected["tick"])]
        elif group == "A_ROUNDING":
            if case["function"] == "roundToTick":
                results = [("roundToTick",round_to_tick(inp["value"],inp["mode"],inp["tick"]),expected)]
            elif case["function"] == "floorShares":
                results = [("floorShares",[floor_shares(v) for v in inp],expected)]
        elif group == "A_TARGET":
            plan = build_plan("LONG" if Decimal(str(inp["entry"])) > Decimal(str(inp["high"])) else "SHORT", inp["high"], inp["low"],
                              inp["atr"], entry_override=inp["entry"])
            results = [(f, plan[f], expected[f]) for f in CHECK_FIELDS if f in expected]
        if not results:
            continue
        tested += 1
        bad = [(key,a,e) for key,a,e in results if not equivalent(a,e)]
        if bad:
            failed += 1
            print(f"FAIL {id_}: {bad[:5]}")
        else:
            print(f"PASS {id_} ({len(results)} fields)")
    print(f"\nTRADE-MATH FIXTURE RESULTS: {tested-failed}/{tested} cases passed")
    print("Other fixture groups (scores, timing, portfolio and full eligibility): NOT IMPLEMENTED")
    if failed:
        raise SystemExit(1)

if __name__ == "__main__":
    main()
