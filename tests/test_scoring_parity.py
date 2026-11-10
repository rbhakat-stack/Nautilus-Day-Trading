"""RB v1.1 Opportunity Scoring parity tests. Run from the project root:

    python tests/test_scoring_parity.py

Three clearly separated sections:

  SECTION 1  GOLDEN component fixtures  (D_SCORE_COMPONENTS 36, D_TIERS 8)
  SECTION 2  GOLDEN full-score fixtures (E_QUEUE_DECISION - score fields only)
  SECTION 3  SUPPLEMENTARY formula cases - NOT golden. Expected values were
             derived from the audited source (opportunityScorer.ts @ c3bbca4)
             for branches that no golden fixture exercises. They prove the
             port follows the audited formula; they are not original outputs.

Expected outputs are read from the read-only audit fixture file and are never
recomputed or edited here. All comparisons are exact (==): the original works
in IEEE-754 doubles and so does the port, so no tolerance is needed.

Fixtures whose `inputs` are null/partial were generated from literals in the
audit harness (reference/RB_v1.1_parity/code/golden.ts). Those input values are
transcribed below as plain data, and the harness file is pinned by SHA-256
(HARNESS_SHA256, cross-checked with the audit manifest) so a silent drift
cannot pass. No harness source text is reproduced in this file.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scoring import opportunity_scorer as S  # noqa: E402
from risk.trade_constructor import build_plan  # noqa: E402  (existing module, read-only use)

REF = ROOT / "reference" / "RB_v1.1_parity"
FIXTURES = REF / "RB_V11_GOLDEN_FIXTURES.json"
HARNESS = REF / "code" / "golden.ts"
MANIFEST = REF / "out" / "NT_AUDIT_MANIFEST.txt"

SCORE_FIELDS = ("components", "setup", "fit", "total", "tier")
STRATEGY_FAIL_CODES = {
    "AFTER_HOURS", "OUTSIDE_ENTRY_WINDOW", "INVALID_CANDLE_DIRECTION",
    "HTF_CONFIRMATION_FAILED", "CHASED_SETUP", "INVALID_TRADE_STRUCTURE",
    "INVALID_INPUT", "EXISTING_SAME_TICKER_POSITION", "RISK_LIMIT",
    "STALE_SETUP", "SETUP_FAILED",
}

# ---------------------------------------------------------------------------
# Synthetic input values used by the audit harness (pinned by HARNESS_SHA256)
# ---------------------------------------------------------------------------
# The synthetic input values below were transcribed from the audit harness and
# checked against it at that exact revision. The harness text itself is private
# and is not reproduced here; instead the file is pinned by SHA-256, so the
# values cannot drift from the harness without this test refusing to run.
HARNESS_SHA256 = "4fe14716cce533281a78d10244909230ed41a6e8b7c5b38fe517e27549764141"

D_BASE = {
    "direction": "LONG", "atr": 0.4, "currentPrice": 99.95, "open": 99.7, "high": 100, "low": 99.6,
    "close": 99.98, "alertTime": "10:00", "chaseDistanceAtr": 0,
    "inputs": {"rvol": 2, "rsi": 60, "vwap": 99.7, "ema9": 99.85, "ema20": 99.65, "close15m": 99.9,
               "ema20_15m": 99.5, "sector": "Tech", "industry": "", "theme": ""},
}
D_TREND_OVERRIDES = {"D-TREND-1": {}, "D-TREND-2": {"currentPrice": 99.69}}
D_CE_CANDIDATE = {"expectedReward": 200, "positionValue": 20000}

SECT = {
    "AAA": ("Technology", "Software", ""), "Q": ("Technology", "Semiconductors", ""),
    "FTNT": ("Technology", "Cyber", ""), "BBB": ("Technology", "Software", ""),
    "CCC": ("Energy", "Oil", ""), "DDD": ("Health", "Pharma", ""),
    "EEE": ("Utilities", "Electric", ""), "ZZZ": ("Materials", "Chem", ""),
}
E_DEFAULT_PRICE = 99.95
E_DEFAULT_VALUES = {"open": 99.7, "high": 100, "low": 99.6, "close": 99.98, "volume": 50000, "atr": 0.4,
                    "ema9": 99.85, "ema20": 99.65, "rsi": 67, "rvol": 3.6, "vwap": 99.7,
                    "vwapAlternative": 99.71, "close15m": 99.9, "ema20_15m": 99.5}
E_TWO_RECORDS = {  # fixture `inputs` is null; values taken from the pinned harness
    "first": {"id": "E-TWO-1", "sym": "AAA", "dir": "LONG", "alertEt": "10:00:01",
              "values": {**E_DEFAULT_VALUES, "rvol": 2.6, "rsi": 62}},
    "second": {"id": "E-TWO-2", "sym": "AAA", "dir": "LONG", "alertEt": "10:05:01",
               "values": {**E_DEFAULT_VALUES, "rvol": 3.6, "rsi": 67}},
}

# Excluded golden fixtures (scoring-relevant groups only) and why.
EXCLUDED = {
    "E-BRK-UNPROT": "needs broker reconciliation (Alpaca broker-only position -> exposure, counted risk); "
                    "that layer is not part of the scorer and is not implemented",
    "E-BRK-PROT": "needs broker reconciliation (verified protective stop -> exposure risk); not implemented",
    "E-BRK-PP": "positionProtection is broker-order logic, not scoring",
}


def with_overrides(base: dict, over: dict | None = None, inputs: dict | None = None) -> dict:
    c = {**base, **(over or {})}
    c["inputs"] = {**base.get("inputs", {}), **(inputs or {})}
    return c


# ---------------------------------------------------------------------------
# Section 1: D fixtures
# ---------------------------------------------------------------------------
def run_d_fixture(case: dict):
    fn, inp, expected = case["function"], case["inputs"], case["output"]
    if fn == "scoreRvol":
        return S.score_rvol(with_overrides(D_BASE, inputs={"rvol": inp}))["points"], expected
    if fn == "scoreMomentum":
        c = with_overrides(D_BASE, {"direction": inp["dir"]}, {"rsi": inp["rsi"]})
        return S.score_momentum(c)["points"], expected
    if fn == "candleMetrics":
        m = S.candle_metrics({"direction": "LONG", "open": inp["o"], "high": inp["h"],
                              "low": inp["l"], "close": inp["c"]})
        return m, expected
    if fn == "scoreLocation":
        c = with_overrides(D_BASE, {"currentPrice": inp["price"], "chaseDistanceAtr": inp["chaseAtr"]})
        return S.score_location(c)["points"], expected
    if fn == "scoreTrend":
        return S.score_trend(with_overrides(D_BASE, D_TREND_OVERRIDES[case["id"]]))["points"], expected
    if fn == "timeBucketFor":
        return S.time_bucket_for(inp), expected
    if fn == "scoreCapitalEfficiency":
        return S.score_capital_efficiency(D_CE_CANDIDATE, inp["eff"])["points"], expected
    if fn == "classifyScore":
        return S.classify_score(inp), expected
    raise KeyError(fn)


# ---------------------------------------------------------------------------
# Section 2: E fixtures (score fields of the Live-Queue row)
# ---------------------------------------------------------------------------
def candidate_from_record(rec: dict, price: float) -> dict:
    """autoCandidate.ts candidateFromRecord, score-relevant fields only."""
    v = rec["values"]
    plan = build_plan(rec["dir"], v["high"], v["low"], v["atr"])  # existing audited trade math
    entry = float(plan["entry"])
    d = 1 if rec["dir"] == "LONG" else -1
    sector, industry, theme = SECT[rec["sym"]]
    return {
        "id": rec["id"], "ticker": rec["sym"], "direction": rec["dir"],
        "open": v["open"], "high": v["high"], "low": v["low"], "close": v["close"], "atr": v["atr"],
        "currentPrice": price,
        "alertTime": rec["alertEt"][:5],  # etParts().hhmm - seconds truncated
        "chaseDistanceAtr": S.clean(d * (price - entry) / v["atr"]),  # only > 0 is used
        "positionValue": float(plan["positionValue"]),
        "plannedRisk": float(plan["maxLoss"]),
        "expectedReward": float(plan["potentialProfit"]),
        "inputs": {"rvol": v["rvol"], "rsi": v["rsi"], "vwap": v["vwap"], "ema9": v["ema9"],
                   "ema20": v["ema20"], "close15m": v["close15m"], "ema20_15m": v["ema20_15m"],
                   "sector": sector, "industry": industry, "theme": theme},
    }


def score_record(rec: dict, price: float, positions: list, expected: dict, peers_other=()):
    c = candidate_from_record(rec, price)
    pf = S.build_portfolio([{**p, "kind": "PENDING" if p.get("pending") else "POSITION"}
                            for p in positions if p.get("status") == "OPEN"])
    # The strategy hard-rule layer is separate and not implemented in this phase.
    # Its verdict is taken from the fixture so that the scorer's own
    # "hard fail -> N/A component, no total" behaviour can be checked.
    fails = [code for code in dict.fromkeys(expected["hardFails"]) if code in STRATEGY_FAIL_CODES]
    peers = S.peer_efficiencies_for(S.efficiency_of(c), peers_other)
    return S.score_opportunity(c, pf, peers, strategy_fail_codes=fails), fails


def diff_score(actual: dict, expected: dict) -> list:
    return [(f, actual[f], expected[f]) for f in SCORE_FIELDS if actual[f] != expected[f]]


# ---------------------------------------------------------------------------
# Section 3: supplementary formula cases (NOT golden)
# ---------------------------------------------------------------------------
FULL = with_overrides(D_BASE, {"ticker": "AAA", "positionValue": 19903.98, "plannedRisk": 83.58,
                               "expectedReward": 167.16},
                      {"sector": "Technology", "industry": "Software"})


def pos(ticker, value, risk, sector, industry="", theme="", direction="LONG", kind="POSITION"):
    return {"ticker": ticker, "direction": direction, "sector": sector, "industry": industry,
            "theme": theme, "positionValue": value, "plannedRisk": risk, "kind": kind}


def _pts(fn, c, *a):
    return fn(c, *a)["points"]


def supplementary_cases():
    T, L, M = S.score_trend, S.score_location, S.score_momentum
    CE, CAP, COR, RSK = (S.score_capital_efficiency, S.score_capital_availability,
                         S.score_correlation, S.score_portfolio_risk)
    c = lambda over=None, inputs=None: with_overrides(FULL, over, inputs)  # noqa: E731
    pf = lambda *e: S.build_portfolio(e)  # noqa: E731
    far9 = {"ema9": 101.0}  # keeps dEMA9 <= 1 so the ext bands are seen without the -1
    cases = [
        # Trend: separation / price-vs-EMA20 / 15m bands and the misalignment cap
        ("SUPP-TREND-sep<0.10", _pts(T, c(inputs={"ema9": 99.67})), 10),
        ("SUPP-TREND-sep<0.25", _pts(T, c(inputs={"ema9": 99.73})), 12),
        ("SUPP-TREND-sep<0.50", _pts(T, c(inputs={"ema9": 99.81})), 14),
        ("SUPP-TREND-sep<=0-cap4", _pts(T, c(inputs={"ema9": 99.60})), 4),
        ("SUPP-TREND-t15<0.25", _pts(T, c(inputs={"close15m": 99.55})), 12),
        ("SUPP-TREND-t15<0.75", _pts(T, c(inputs={"close15m": 99.7})), 14),
        ("SUPP-TREND-t15<=0-cap4", _pts(T, c(inputs={"close15m": 99.4})), 4),
        ("SUPP-TREND-p20<0.25", _pts(T, c({"currentPrice": 99.72})), 12),
        ("SUPP-TREND-p20<0.75", _pts(T, c({"currentPrice": 99.8})), 14),
        ("SUPP-TREND-missing-vwap", S.score_trend(c(inputs={"vwap": None}))["missing"], True),
        ("SUPP-TREND-atr0-missing", S.score_trend(c({"atr": 0}))["missing"], True),
        # Location: every ext band, EMA9 stretch penalty, chase deduction, clamp
        ("SUPP-LOC-ext<0", _pts(L, c({"currentPrice": 99.6})), 4),
        ("SUPP-LOC-ext<=2.0", _pts(L, c({"currentPrice": 100.35}, far9)), 7),
        ("SUPP-LOC-ext<=2.5", _pts(L, c({"currentPrice": 100.6}, far9)), 5),
        ("SUPP-LOC-ext<=3.5", _pts(L, c({"currentPrice": 100.9}, far9)), 3),
        ("SUPP-LOC-ext>3.5", _pts(L, c({"currentPrice": 101.2}, far9)), 1),
        ("SUPP-LOC-ema9-penalty", _pts(L, c({"currentPrice": 100.35})), 6),
        ("SUPP-LOC-clamp0", _pts(L, c({"currentPrice": 101.2})), 0),
        ("SUPP-LOC-chase0.30", _pts(L, c({"chaseDistanceAtr": 0.3})), 8),
        ("SUPP-LOC-chase0.0625-JS-half-up", _pts(L, c({"chaseDistanceAtr": 0.0625})), 9),
        ("SUPP-LOC-chase-negative-ignored", _pts(L, c({"chaseDistanceAtr": -0.175})), 10),
        ("SUPP-LOC-chase-None", _pts(L, c({"chaseDistanceAtr": None})), 10),
        ("SUPP-LOC-missing-ema9", S.score_location(c(inputs={"ema9": None}))["missing"], True),
        # Momentum: remaining band edges, SHORT mirror, missing
        ("SUPP-RSI-LONG-60", _pts(M, c(inputs={"rsi": 60})), 9),
        ("SUPP-RSI-LONG-59.99", _pts(M, c(inputs={"rsi": 59.99})), 6),
        ("SUPP-RSI-LONG-64.99", _pts(M, c(inputs={"rsi": 64.99})), 9),
        ("SUPP-RSI-LONG-69.99", _pts(M, c(inputs={"rsi": 69.99})), 10),
        ("SUPP-RSI-LONG-74.99", _pts(M, c(inputs={"rsi": 74.99})), 7),
        ("SUPP-RSI-LONG-100", _pts(M, c(inputs={"rsi": 100})), 4),
        ("SUPP-RSI-SHORT-40", _pts(M, c({"direction": "SHORT"}, {"rsi": 40})), 9),
        ("SUPP-RSI-SHORT-30", _pts(M, c({"direction": "SHORT"}, {"rsi": 30})), 7),
        ("SUPP-RSI-SHORT-25", _pts(M, c({"direction": "SHORT"}, {"rsi": 25})), 4),
        ("SUPP-RSI-SHORT-0", _pts(M, c({"direction": "SHORT"}, {"rsi": 0})), 4),
        ("SUPP-RSI-SHORT-55-out", _pts(M, c({"direction": "SHORT"}, {"rsi": 55})), 0),
        ("SUPP-RSI-missing", S.score_momentum(c(inputs={"rsi": None}))["missing"], True),
        ("SUPP-RVOL-missing", S.score_rvol(c(inputs={"rvol": None}))["missing"], True),
        ("SUPP-RVOL-NaN-missing", S.score_rvol(c(inputs={"rvol": float("nan")}))["missing"], True),
        # Candle: SHORT mirror, zero range, x.5 tie, non-directional cap
        ("SUPP-CANDLE-SHORT", S.candle_metrics({"direction": "SHORT", "open": 100.3, "high": 100.4,
                                                "low": 100.0, "close": 100.02})["base"], 8),
        ("SUPP-CANDLE-SHORT-lower-wick", S.candle_metrics({"direction": "SHORT", "open": 100.3, "high": 100.4,
                                                           "low": 100.0, "close": 100.25})["base"], 2),
        ("SUPP-CANDLE-zero-range", S.candle_metrics({"direction": "LONG", "open": 50, "high": 50,
                                                     "low": 50, "close": 50})["base"], 0),
        ("SUPP-CANDLE-6.5-JS-half-up", S.candle_metrics({"direction": "LONG", "open": 99.72, "high": 100,
                                                         "low": 99.6, "close": 99.92})["base"], 7),
        ("SUPP-CANDLE-doji-at-high", S.candle_metrics({"direction": "LONG", "open": 100, "high": 100,
                                                       "low": 99.6, "close": 100})["base"], 2),
        ("SUPP-CANDLE-red-for-LONG", S.candle_metrics({"direction": "LONG", "open": 99.98, "high": 100,
                                                       "low": 99.6, "close": 99.7})["base"], 1),
        # Time: unparsable / seconds are not accepted by the original toMinutes
        ("SUPP-TIME-HH:MM:SS-rejected", S.time_bucket_for("10:00:01"), None),
        ("SUPP-TIME-None", S.score_time(c({"alertTime": None}))["missing"], True),
        ("SUPP-TIME-15:30-bucket-is-8", _pts(S.score_time, c({"alertTime": "15:30"})), 8),
        # Capital efficiency: percentile, ties, JS rounding, missing position value
        ("SUPP-CE-middle-of-3", _pts(CE, {"expectedReward": 160, "positionValue": 20000}, [0.005, 0.008, 0.01]), 6),
        ("SUPP-CE-worst-of-3", _pts(CE, {"expectedReward": 100, "positionValue": 20000}, [0.005, 0.008, 0.01]), 2),
        ("SUPP-CE-all-tied", _pts(CE, {"expectedReward": 200, "positionValue": 20000}, [0.01, 0.01, 0.01]), 6),
        ("SUPP-CE-2nd-of-4", _pts(CE, {"expectedReward": 120, "positionValue": 20000}, [0.004, 0.006, 0.008, 0.01]), 5),
        ("SUPP-CE-tied-lowest-of-3", _pts(CE, {"expectedReward": 100, "positionValue": 20000}, [0.005, 0.005, 0.01]), 4),
        ("SUPP-CE-2.5-JS-half-up", _pts(CE, {"expectedReward": 100, "positionValue": 20000},
                                        [0.005, 0.005, 0.01, 0.011, 0.012, 0.013, 0.014, 0.015, 0.016]), 3),
        ("SUPP-CE-pv0-missing", S.score_capital_efficiency({"expectedReward": 1, "positionValue": 0}, [0.01])["missing"], True),
        # Capacity: usage bands, pending reservations, slot and size limits
        ("SUPP-CAP-used<=0.5", _pts(CAP, c(), pf()), 8),
        ("SUPP-CAP-used<=0.8", _pts(CAP, c(), pf(pos("CCC", 50000, 100, "Energy"))), 5),
        ("SUPP-CAP-used>0.8", _pts(CAP, c(), pf(pos("CCC", 58000, 100, "Energy"))), 2),
        ("SUPP-CAP-pending-reserves", _pts(CAP, c(), pf(pos("CCC", 30000, 100, "Energy"),
                                                       pos("DDD", 20000, 100, "Health", kind="PENDING"))), 5),
        ("SUPP-CAP-3open+1pending-slots", _pts(CAP, c(), pf(pos("CCC", 1000, 10, "Energy"), pos("DDD", 1000, 10, "Health"),
                                                            pos("EEE", 1000, 10, "Utilities"),
                                                            pos("ZZZ", 1000, 10, "Materials", kind="PENDING"))), 0),
        ("SUPP-CAP-size>20000", _pts(CAP, c({"positionValue": 25000}), pf()), 0),
        # Correlation: sector, theme, opposite direction, normalisation, missing sector
        ("SUPP-COR-none", _pts(COR, c(), pf(pos("CCC", 5000, 50, "Energy", "Oil"))), 7),
        ("SUPP-COR-sector-only", _pts(COR, c(), pf(pos("FTNT", 5000, 50, "Technology", "Cyber"))), 4),
        ("SUPP-COR-sector-empty-industry", _pts(COR, c(inputs={"industry": ""}), pf(pos("XXX", 5000, 50, "Technology"))), 4),
        ("SUPP-COR-same-theme", _pts(COR, c(inputs={"theme": "AI"}), pf(pos("CCC", 5000, 50, "Energy", "Oil", "ai "))), 0),
        ("SUPP-COR-opposite-dir-still-blocks", _pts(COR, c(), pf(pos("BBB", 5000, 50, "Technology", "Software", direction="SHORT"))), 0),
        ("SUPP-COR-case-whitespace", _pts(COR, c(), pf(pos("BBB", 5000, 50, "TECHNOLOGY", " software "))), 0),
        ("SUPP-COR-same-ticker", _pts(COR, c(), pf(pos("aaa", 5000, 50, "Other", "Other"))), 0),
        ("SUPP-COR-pending-counts", _pts(COR, c(), pf(pos("BBB", 5000, 50, "Technology", "Software", kind="PENDING"))), 0),
        ("SUPP-COR-sector-missing", S.score_correlation(c(inputs={"sector": "  "}), pf())["missing"], True),
        # Portfolio risk: heat bands (limit $1,000; new risk $83.58)
        ("SUPP-RISK-<=0.50", _pts(RSK, c(), pf(pos("CCC", 5000, 416.42, "Energy"))), 5),
        ("SUPP-RISK-<=0.75", _pts(RSK, c(), pf(pos("CCC", 5000, 500, "Energy"))), 4),
        ("SUPP-RISK-<=0.90", _pts(RSK, c(), pf(pos("CCC", 5000, 700, "Energy"))), 3),
        ("SUPP-RISK-<=1.00", _pts(RSK, c(), pf(pos("CCC", 5000, 850, "Energy"))), 2),
        ("SUPP-RISK-exactly-1.00", _pts(RSK, c(), pf(pos("CCC", 5000, 916.42, "Energy"))), 2),
        ("SUPP-RISK-pending-heat", _pts(RSK, c(), pf(pos("CCC", 5000, 500, "Energy"),
                                                     pos("DDD", 5000, 450, "Health", kind="PENDING"))), 0),
    ]
    # Totals / completeness / fail-closed behaviour
    full = S.score_opportunity(c(), pf(), [S.efficiency_of(c())])
    incomplete = S.score_opportunity(c(inputs={"sector": ""}), pf(), [S.efficiency_of(c())])
    rvol0 = S.score_opportunity(c(inputs={"rvol": 0}), pf(), [S.efficiency_of(c())])
    htf = S.score_opportunity(c(), pf(), [S.efficiency_of(c())], strategy_fail_codes=["HTF_CONFIRMATION_FAILED"])
    chased = S.score_opportunity(c(), pf(), [S.efficiency_of(c())], strategy_fail_codes=["CHASED_SETUP"])
    cases += [
        ("SUPP-TOTAL-setup+fit", (full["setup"], full["fit"], full["total"], full["tier"]), (61, 26, 87, "HIGH_PRIORITY")),
        ("SUPP-TOTAL-missing-sector-not-scored", (incomplete["total"], incomplete["tier"], incomplete["missing"]),
         (None, None, ["Sector"])),
        ("SUPP-TOTAL-rvol0-is-missing", (rvol0["total"], rvol0["missing"]), (None, ["RVOL(20)"])),
        ("SUPP-TOTAL-HTF-fail-trend-NA", (htf["total"], htf["components"]["trend"]), (None, 0)),
        ("SUPP-TOTAL-chased-location-NA", (chased["total"], chased["components"]["location"]), (None, 0)),
        ("SUPP-MIN-SCORE-is-85", (S.MIN_TRADE_SCORE, S.meets_min_trade_score(84.9), S.meets_min_trade_score(85),
                                  S.meets_min_trade_score(None)), (85, False, True, False)),
        ("SUPP-NEVER-AUTHORIZES", full["authorization"].startswith("NOT AUTHORIZED"), True),
        ("SUPP-MAXES-sum-100", (sum(S.DEFAULT_MAX.values()), sum(S.DEFAULT_MAX[k] for k in S.SETUP_KEYS),
                                sum(S.DEFAULT_MAX[k] for k in S.FIT_KEYS)), (100, 70, 30)),
    ]
    return cases


# ---------------------------------------------------------------------------
def main() -> None:
    for path in (FIXTURES, HARNESS, MANIFEST):
        if not path.exists():
            raise SystemExit(f"Reference artifact missing: {path}")
    raw = FIXTURES.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest not in MANIFEST.read_text(encoding="utf-8"):
        raise SystemExit(f"Golden fixture file does not match the audit manifest (sha256 {digest}). Refusing to run.")
    harness_digest = hashlib.sha256(HARNESS.read_bytes()).hexdigest()
    if harness_digest != HARNESS_SHA256 or harness_digest not in MANIFEST.read_text(encoding="utf-8"):
        raise SystemExit(f"Audit harness golden.ts does not match the pinned revision (sha256 {harness_digest}). "
                         "The transcribed input values can no longer be trusted. Refusing to run.")
    fixtures = json.loads(raw.decode("utf-8"))["fixtures"]
    if len(fixtures) != 139:
        raise SystemExit(f"Expected 139 golden fixtures, found {len(fixtures)}")

    passed, failed, excluded, out_of_scope = [], [], [], {}
    conditional = []

    print("SECTION 1 - GOLDEN component fixtures (D_SCORE_COMPONENTS, D_TIERS)")
    for case in fixtures:
        if case["group"] not in ("D_SCORE_COMPONENTS", "D_TIERS"):
            continue
        actual, expected = run_d_fixture(case)
        ok = actual == expected
        (passed if ok else failed).append(case["id"])
        print(f"{'PASS' if ok else 'FAIL'} {case['id']}" + ("" if ok else f": actual={actual!r} expected={expected!r}"))

    print("\nSECTION 2 - GOLDEN full-score fixtures (E_QUEUE_DECISION: components, setup, fit, total, tier)")
    for case in fixtures:
        group, id_ = case["group"], case["id"]
        if group in ("D_SCORE_COMPONENTS", "D_TIERS"):
            continue
        if id_ in EXCLUDED:
            excluded.append(id_)
            print(f"EXCLUDED {id_}: {EXCLUDED[id_]}")
            continue
        if group != "E_QUEUE_DECISION":
            out_of_scope[group] = out_of_scope.get(group, 0) + 1
            continue
        if id_ == "E-TWO":
            subs = []
            effs = {k: S.efficiency_of(candidate_from_record(r, E_DEFAULT_PRICE)) for k, r in E_TWO_RECORDS.items()}
            for key, rec in E_TWO_RECORDS.items():
                others = [e for k, e in effs.items() if k != key]  # both alerts are inside the 10-minute window
                actual, _ = score_record(rec, E_DEFAULT_PRICE, [], case["output"][key], others)
                subs.append((key, diff_score(actual, case["output"][key])))
            bad = [(k, d) for k, d in subs if d]
            (failed if bad else passed).append(id_)
            print(f"{'FAIL' if bad else 'PASS'} {id_} (both records; inputs reconstructed from golden.ts)"
                  + (f": {bad}" if bad else ""))
            continue
        rec = case["inputs"]["records"][0]
        extra = case["inputs"]["extra"]
        actual, fails = score_record(rec, extra.get("price", E_DEFAULT_PRICE), extra.get("positions", []), case["output"])
        bad = diff_score(actual, case["output"])
        (failed if bad else passed).append(id_)
        note = ""
        if fails:
            conditional.append(id_)
            note = f" (strategy hard-fail codes {fails} supplied from the fixture; hard-rule layer not implemented)"
        print(f"{'FAIL' if bad else 'PASS'} {id_}{note}" + (f": {bad}" if bad else ""))

    print("\nSECTION 3 - SUPPLEMENTARY formula cases (NOT golden; derived from the audited source)")
    supp_pass, supp_fail = 0, []
    for id_, actual, expected in supplementary_cases():
        ok = actual == expected and type(actual) is type(expected) or (
            isinstance(actual, (int, float)) and isinstance(expected, (int, float))
            and not isinstance(actual, bool) and actual == expected)
        if ok:
            supp_pass += 1
        else:
            supp_fail.append(id_)
        print(f"{'PASS' if ok else 'FAIL'} {id_}" + ("" if ok else f": actual={actual!r} expected={expected!r}"))

    print("\n================ SCORING PARITY SUMMARY ================")
    print(f"Golden scoring fixtures PASSED : {len(passed)}")
    print(f"Golden scoring fixtures FAILED : {len(failed)} {failed if failed else ''}")
    print(f"Golden fixtures EXCLUDED       : {len(excluded)} {excluded}")
    print(f"  of the passes, conditional on fixture-supplied hard-fail codes: {conditional}")
    print(f"Other groups, not scoring (not run here): {out_of_scope}")
    print(f"Supplementary (non-golden) cases: {supp_pass} passed, {len(supp_fail)} failed {supp_fail if supp_fail else ''}")
    print("Score-only comparison: decision, ticket, gate, lifecycle and Policy A/B fields are NOT compared.")
    print("FULL RB v1.1 SCORING PARITY IS NOT CLAIMED - see the verification gaps in the report.")
    if failed or supp_fail:
        raise SystemExit(1)


def test_scoring_parity():  # pytest entry point
    main()


if __name__ == "__main__":
    main()
