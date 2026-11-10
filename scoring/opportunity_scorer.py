"""RB Trade Decider v1.1 ACTIVE Opportunity Score (100 points) - formula port.

Source of truth: audited production commit c3bbca4
  calculator/src/engine/ranker/opportunityScorer.ts
  calculator/src/engine/ranker/rankerSettings.ts
  calculator/src/engine/ranker/correlationRules.ts
  calculator/src/engine/ranker/portfolioAllocator.ts  (buildPortfolio, checkFit)
  calculator/src/engine/ranker/candidateRanker.ts     (totals, tiers, missing, N/A)
as documented in reference/RB_v1.1_parity (RB_V11_FORMULA_PARITY_SPEC.md Part C
and the bundled original source in code/golden.mjs).

SCOPE
  * A score is NOT an authorization to trade. Hard rules, allocation, data
    review, lifecycle and order submission are separate layers and are not
    implemented here. Every result carries AUTHORIZATION = NOT AUTHORIZED.
  * Policy A/B (TrendSpider RVOL qualification, minimum 80) is NOT implemented.
    The minimum trade score is 85 and cannot be lowered through this module.
  * v1.2 SHADOW scoring (QUALIFIED_FLOOR) is NOT implemented.
  * No broker, network, TrendSpider, Alpaca or NautilusTrader dependency.
    Python standard library only.

NUMERICS
  The original runs on IEEE-754 doubles. This port deliberately uses Python
  floats (the same doubles) and re-implements JavaScript Math.round, because
  Python's round() is banker's rounding and would differ on .5 ties.
"""
from __future__ import annotations

import math
import re
from typing import Any, Iterable, Mapping, Sequence

AUTHORIZATION = "NOT AUTHORIZED - SCORE ONLY (hard rules are a separate layer)"

# --------------------------------------------------------------------------
# Settings (rankerSettings.ts RANKER_DEFAULTS) - frozen v1.1 values
# --------------------------------------------------------------------------
DEFAULT_MAX: dict[str, int] = {
    "trend": 15, "rvol": 15, "momentum": 10, "candle": 10, "location": 10,
    "time": 10, "capitalEfficiency": 10, "capitalAvailability": 8,
    "correlation": 7, "portfolioRisk": 5,
}
SETUP_KEYS = ("trend", "rvol", "momentum", "candle", "location", "time")
FIT_KEYS = ("capitalEfficiency", "capitalAvailability", "correlation", "portfolioRisk")
COMPONENT_ORDER = SETUP_KEYS + FIT_KEYS
SETUP_CAP, FIT_CAP, TOTAL_CAP = 70, 30, 100

RVOL_BANDS = (  # last band with rvol >= min wins
    (1.5, 6, "NORMAL"), (2.0, 9, "ELEVATED"),
    (2.5, 12, "STRONG"), (3.5, 15, "EXCEPTIONAL"),
)
RSI_BANDS_LONG = (  # from <= eff < to ; SHORT uses eff = 100 - RSI
    (55, 60, 6), (60, 65, 9), (65, 70, 10), (70, 75, 7), (75, 101, 4),
)
TIME_BUCKETS = (  # last bucket whose start <= alert HH:MM
    ("09:45", "Primary window 9:45–11:30", 10),
    ("11:30", "Midday 11:30–2:00", 6),
    ("14:00", "Afternoon 2:00–3:30", 8),
)
GRADES = {"elite": 90, "high": 85, "watchlist": 80, "low": 75}
MIN_TRADE_SCORE = GRADES["high"]  # 85. Not configurable here by design.
MIN_CANDIDATES_FOR_RELATIVE = 3

PORTFOLIO_DEFAULTS = {
    "accountEquity": 100000.0,      # configured equity, never broker equity
    "maxPositionValue": 20000.0,
    "maxPositions": 4,
    "riskPerTradePct": 0.0025,
    "heatPct": 0.01,
    "liquidityReservePct": 0.2,
}
CORRELATION_POLICY = {
    "maxHighlyCorrelated": 1, "hardBlock": True, "allowOppositeDirection": False,
}

# Strategy hard-fail code -> component shown as N/A (0 points). candidateRanker.ts hardFailNA.
HARD_FAIL_NA = {
    "AFTER_HOURS": "time",
    "OUTSIDE_ENTRY_WINDOW": "time",
    "INVALID_CANDLE_DIRECTION": "candle",
    "HTF_CONFIRMATION_FAILED": "trend",
    "CHASED_SETUP": "location",
}

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


# --------------------------------------------------------------------------
# JavaScript-compatible numerics
# --------------------------------------------------------------------------
def js_round(x: float) -> float:
    """JavaScript Math.round: nearest integer, ties toward +infinity."""
    if not math.isfinite(x):
        return x
    f = math.floor(x)
    return float(f + 1) if (x - f) >= 0.5 else float(f)


def clean(x: float) -> float:
    """rounding.ts clean(): Math.round(x * 1e8) / 1e8."""
    return js_round(x * 1e8) / 1e8


def round1(x: float) -> float:
    """Math.round(x * 10) / 10."""
    return js_round(x * 10) / 10


def is_num(v: Any) -> bool:
    """typeof v === 'number' && Number.isFinite(v). Booleans/strings/None are not numbers."""
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _gt0(v: Any) -> bool:
    """JS `v > 0` for a possibly-missing value (None/NaN -> False)."""
    return is_num(v) and v > 0


def to_minutes(hhmm: Any) -> float:
    """rules.ts toMinutes: strict HH:MM (24h); anything else is NaN."""
    if isinstance(hhmm, str) and _HHMM.match(hhmm):
        return float(int(hhmm[0:2]) * 60 + int(hhmm[3:5]))
    return math.nan


def _dir_sign(direction: str) -> int:
    if direction not in ("LONG", "SHORT"):
        raise ValueError("direction must be LONG or SHORT")
    return 1 if direction == "LONG" else -1


def _get(c: Mapping[str, Any], key: str) -> Any:
    return c.get(key)


def _inputs(c: Mapping[str, Any]) -> Mapping[str, Any]:
    return c.get("inputs") or {}


def _text(v: Any) -> str:
    return v if isinstance(v, str) else ""


# --------------------------------------------------------------------------
# Component container
# --------------------------------------------------------------------------
def _make(key: str, base: float, *, weights: Mapping[str, float] | None = None,
          missing: bool = False, detail: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """opportunityScorer.ts make(): points = round1(clamp(base, 0, MAX) * weight / MAX)."""
    dmax = DEFAULT_MAX[key]
    weight = (weights or DEFAULT_MAX)[key]
    points = round1(max(0, min(base, dmax)) * weight / dmax)
    return {"key": key, "base": base, "points": points, "max": weight,
            "missing": missing, "na": None, "detail": dict(detail or {})}


def _missing(key: str, what: str, weights: Mapping[str, float] | None = None) -> dict[str, Any]:
    return _make(key, 0, weights=weights, missing=True, detail={"missingInput": what})


# --------------------------------------------------------------------------
# 1. Trend (15)
# --------------------------------------------------------------------------
def score_trend(c: Mapping[str, Any], weights: Mapping[str, float] | None = None) -> dict[str, Any]:
    i = _inputs(c)
    vwap, ema9, ema20 = i.get("vwap"), i.get("ema9"), i.get("ema20")
    close15m, ema20_15m = i.get("close15m"), i.get("ema20_15m")
    atr = _get(c, "atr")
    if not all(is_num(v) for v in (vwap, ema9, ema20, close15m, ema20_15m)) or not _gt0(atr):
        return _missing("trend", "VWAP, EMA9, EMA20, 15m Close and 15m EMA20", weights)
    d = _dir_sign(c["direction"])
    price = c["currentPrice"]
    sep = clean(d * (ema9 - ema20) / atr)
    p20 = clean(d * (price - ema20) / atr)
    vw = clean(d * (price - vwap) / atr)
    t15 = clean(d * (close15m - ema20_15m) / atr)  # normalised by the 5m ATR
    sep_pts = 0 if sep <= 0 else 1 if sep < 0.1 else 3 if sep < 0.25 else 5 if sep < 0.5 else 6
    p20_pts = 0 if p20 <= 0 else 1 if p20 < 0.25 else 3 if p20 < 0.75 else 4
    t15_pts = 0 if t15 <= 0 else 2 if t15 < 0.25 else 4 if t15 < 0.75 else 5
    base = sep_pts + p20_pts + t15_pts
    misaligned = vw <= 0 or sep <= 0 or t15 <= 0
    if misaligned:
        base = min(base, 4)
    return _make("trend", base, weights=weights, detail={
        "sep": sep, "p20": p20, "vwapSide": vw, "t15": t15,
        "sepPts": sep_pts, "p20Pts": p20_pts, "t15Pts": t15_pts, "misaligned": misaligned})


# --------------------------------------------------------------------------
# 2. RVOL (15)
# --------------------------------------------------------------------------
def score_rvol(c: Mapping[str, Any], weights: Mapping[str, float] | None = None) -> dict[str, Any]:
    if c.get("qualification"):
        # v1.2 SHADOW / TrendSpider QUALIFIED_FLOOR path - excluded from v1.1 parity.
        raise NotImplementedError("TrendSpider-qualified RVOL (QUALIFIED_FLOOR) is not part of v1.1 ACTIVE")
    r = _inputs(c).get("rvol")
    if not is_num(r):
        return _missing("rvol", "RVOL(20)", weights)
    base, label = 0, "BELOW ALERT THRESHOLD"
    for mn, pts, lbl in RVOL_BANDS:
        if r >= mn:
            base, label = pts, lbl
    return _make("rvol", base, weights=weights, detail={"rvol": r, "band": label})


# --------------------------------------------------------------------------
# 3. Momentum (10)
# --------------------------------------------------------------------------
def score_momentum(c: Mapping[str, Any], weights: Mapping[str, float] | None = None) -> dict[str, Any]:
    rsi = _inputs(c).get("rsi")
    if not is_num(rsi):
        return _missing("momentum", "RSI(14)", weights)
    _dir_sign(c["direction"])
    eff = rsi if c["direction"] == "LONG" else 100 - rsi
    base, band = 0, None
    for lo, hi, pts in RSI_BANDS_LONG:
        if eff >= lo and eff < hi:
            base, band = pts, (lo, hi)
            break
    return _make("momentum", base, weights=weights, detail={"rsi": rsi, "effective": eff, "band": band})


# --------------------------------------------------------------------------
# 4. Candle (10)
# --------------------------------------------------------------------------
def candle_metrics(c: Mapping[str, Any]) -> dict[str, Any]:
    O, H, L, C = c["open"], c["high"], c["low"], c["close"]
    rng = clean(H - L)
    body = clean(abs(C - O))
    upper = clean(H - max(O, C))
    lower = clean(min(O, C) - L)
    is_long = c["direction"] == "LONG"
    _dir_sign(c["direction"])
    directional = C > O if is_long else C < O
    if rng <= 0:
        return {"range": rng, "body": body, "bodyRatio": 0, "upperWick": upper, "lowerWick": lower,
                "opposingWickRatio": 0, "closeLocation": 0, "directional": directional,
                "classification": "Rejection Risk", "base": 0}
    body_ratio = clean(body / rng)
    opposing = clean((upper if is_long else lower) / rng)
    close_loc = clean((C - L) / rng if is_long else (H - C) / rng)
    if not directional:
        base = min(2, js_round(2 * close_loc))
    elif opposing >= 0.5:
        base = 2
    else:
        base = js_round(10 * (0.5 * body_ratio + 0.5 * close_loc))
    base = int(base)
    classification = ("Strong Breakout Candle" if base >= 9 else "Acceptable" if base >= 6
                      else "Weak" if base >= 3 else "Rejection Risk")
    return {"range": rng, "body": body, "bodyRatio": body_ratio, "upperWick": upper,
            "lowerWick": lower, "opposingWickRatio": opposing, "closeLocation": close_loc,
            "directional": directional, "classification": classification, "base": base}


def score_candle(c: Mapping[str, Any], weights: Mapping[str, float] | None = None) -> dict[str, Any]:
    # The original has no missing-input branch for OHLC (the snapshot guarantees
    # them). Fail closed rather than invent one.
    if not all(is_num(c.get(k)) for k in ("open", "high", "low", "close")):
        raise ValueError("Signal candle OHLC must be finite numbers")
    m = candle_metrics(c)
    return _make("candle", m["base"], weights=weights, detail=m)


# --------------------------------------------------------------------------
# 5. Location (10)
# --------------------------------------------------------------------------
def score_location(c: Mapping[str, Any], weights: Mapping[str, float] | None = None) -> dict[str, Any]:
    i = _inputs(c)
    vwap, ema9, ema20 = i.get("vwap"), i.get("ema9"), i.get("ema20")
    atr = _get(c, "atr")
    if not all(is_num(v) for v in (vwap, ema9, ema20)) or not _gt0(atr):
        return _missing("location", "VWAP, EMA9 and EMA20", weights)
    d = _dir_sign(c["direction"])
    price = c["currentPrice"]
    d_v = clean(d * (price - vwap) / atr)
    d_20 = clean(d * (price - ema20) / atr)
    d_9 = clean(d * (price - ema9) / atr)
    ext = max(d_v, d_20)
    base = (4 if ext < 0 else 10 if ext <= 1 else 9 if ext <= 1.5 else 7 if ext <= 2
            else 5 if ext <= 2.5 else 3 if ext <= 3.5 else 1)
    ema9_penalty = d_9 > 1
    if ema9_penalty:
        base -= 1
    chase = c.get("chaseDistanceAtr")
    chase = chase if is_num(chase) else 0  # `?? 0`
    chase_deduction = 0
    if chase > 0:
        chase_deduction = int(js_round(8 * chase))
        base -= chase_deduction
    base = max(0, min(10, base))
    return _make("location", base, weights=weights, detail={
        "dVwap": d_v, "dEma20": d_20, "dEma9": d_9, "ext": ext,
        "ema9Penalty": ema9_penalty, "chaseAtr": chase, "chaseDeduction": chase_deduction})


# --------------------------------------------------------------------------
# 6. Time (10)
# --------------------------------------------------------------------------
def time_bucket_for(alert_time: Any) -> dict[str, Any] | None:
    t = to_minutes(alert_time)
    if not math.isfinite(t):
        return None
    bucket = None
    for start, label, pts in TIME_BUCKETS:
        if to_minutes(start) <= t:
            bucket = {"start": start, "label": label, "points": pts}
    return bucket


def score_time(c: Mapping[str, Any], weights: Mapping[str, float] | None = None) -> dict[str, Any]:
    """Alert HH:MM (ET, seconds truncated). NOTE: this bucket function alone gives 8
    points at/after 15:30; the entry-window hard rule (separate layer) is what
    turns that into N/A - see apply_hard_fail_na()."""
    b = time_bucket_for(c.get("alertTime"))
    if not b:
        return _missing("time", "alert time inside the entry window", weights)
    return _make("time", b["points"], weights=weights, detail=b)


# --------------------------------------------------------------------------
# Portfolio state (portfolioAllocator.ts buildPortfolio / checkFit)
# --------------------------------------------------------------------------
def build_portfolio(exposures: Iterable[Mapping[str, Any]] = (), *,
                    settings: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Portfolio state WITHOUT the candidate being scored.

    Each exposure: ticker, direction, sector, industry, theme, positionValue,
    plannedRisk, and kind = "POSITION" (open/filled) or "PENDING" (working
    entry order). The caller is responsible for supplying verified exposure
    (including broker-only positions); reconciliation is a separate layer.
    """
    p = {**PORTFOLIO_DEFAULTS, **(settings or {})}
    exps = []
    for e in exposures:
        kind = e.get("kind") or ("PENDING" if e.get("pending") else "POSITION")
        if kind not in ("POSITION", "PENDING"):
            raise ValueError("exposure kind must be POSITION or PENDING")
        if not (is_num(e.get("positionValue")) and is_num(e.get("plannedRisk"))):
            raise ValueError("exposure positionValue and plannedRisk must be finite numbers")
        exps.append({"id": e.get("id"), "kind": kind, "ticker": _text(e.get("ticker")),
                     "direction": e.get("direction"), "sector": _text(e.get("sector")),
                     "industry": _text(e.get("industry")), "theme": _text(e.get("theme")),
                     "positionValue": e["positionValue"], "plannedRisk": e["plannedRisk"]})

    def total(kind: str, field: str) -> float:
        acc = 0.0
        for e in exps:
            if e["kind"] == kind:
                acc = acc + e[field]
        return clean(acc)

    usable = clean(p["accountEquity"] * (1 - p["liquidityReservePct"]))
    deployed, reserved = total("POSITION", "positionValue"), total("PENDING", "positionValue")
    heat_open, heat_pending = total("POSITION", "plannedRisk"), total("PENDING", "plannedRisk")
    n_open = sum(1 for e in exps if e["kind"] == "POSITION")
    n_pending = sum(1 for e in exps if e["kind"] == "PENDING")
    return {
        "equity": p["accountEquity"], "usableAllocation": usable,
        "maxPositionValue": p["maxPositionValue"], "maxPositions": p["maxPositions"],
        "deployed": deployed, "reserved": reserved,
        "available": clean(usable - deployed - reserved),
        "openPositions": n_open, "pendingOrders": n_pending, "slotsUsed": n_open + n_pending,
        "heatOpen": heat_open, "heatCommitted": clean(heat_open + heat_pending),
        "heatLimit": clean(p["accountEquity"] * p["heatPct"]),
        "perTradeRiskLimit": clean(p["accountEquity"] * p["riskPerTradePct"]),
        "exposures": exps,
    }


def correlation_level(a: Mapping[str, Any], b: Mapping[str, Any]) -> str:
    def norm(s: Any) -> str:
        return _text(s).strip().lower()
    if norm(a.get("ticker")) and norm(a.get("ticker")) == norm(b.get("ticker")):
        return "HIGH"
    if norm(a.get("industry")) and norm(a.get("industry")) == norm(b.get("industry")):
        return "HIGH"
    if norm(a.get("theme")) and norm(a.get("theme")) == norm(b.get("theme")):
        return "HIGH"
    if norm(a.get("sector")) and norm(a.get("sector")) == norm(b.get("sector")):
        return "SECTOR"
    return "NONE"


def assess_correlation(candidate: Mapping[str, Any], exposures: Sequence[Mapping[str, Any]],
                       policy: Mapping[str, Any] | None = None) -> dict[str, Any]:
    policy = policy or CORRELATION_POLICY
    high, sector, opposite = [], [], []
    for e in exposures:
        lvl = correlation_level(candidate, e)
        if lvl == "NONE":
            continue
        same_dir = e.get("direction") == candidate.get("direction")
        if not same_dir and policy["allowOppositeDirection"]:
            opposite.append(e.get("ticker"))
            continue
        (high if lvl == "HIGH" else sector).append(e.get("ticker"))
    blocked = bool(policy["hardBlock"]) and len(high) >= policy["maxHighlyCorrelated"]
    level = "HIGH" if high else "SECTOR" if sector else "NONE"
    base = 0 if blocked else 1 if level == "HIGH" else 4 if level == "SECTOR" else 7
    return {"level": level, "highWith": high, "sectorWith": sector,
            "oppositeWith": opposite, "blocked": blocked, "basePoints": base}


def _as_classified(c: Mapping[str, Any]) -> dict[str, Any]:
    i = _inputs(c)
    return {"ticker": _text(c.get("ticker")), "direction": c.get("direction"),
            "sector": _text(i.get("sector")), "industry": _text(i.get("industry")),
            "theme": _text(i.get("theme")), "positionValue": c.get("positionValue"),
            "plannedRisk": c.get("plannedRisk")}


def check_fit(trade: Mapping[str, Any], pf: Mapping[str, Any]) -> dict[str, Any]:
    corr = assess_correlation(trade, pf["exposures"])
    projected = clean(pf["heatCommitted"] + trade["plannedRisk"])
    return {
        "slotOk": pf["slotsUsed"] < pf["maxPositions"],
        "capitalOk": trade["positionValue"] <= pf["available"] + 1e-9,
        "sizeOk": trade["positionValue"] <= pf["maxPositionValue"] + 1e-9,
        "heatOk": projected <= pf["heatLimit"] + 1e-9,
        "correlationOk": not corr["blocked"],
        "correlationBlockers": corr["highWith"],
        "projectedHeat": projected,
    }


# --------------------------------------------------------------------------
# 7. Capital efficiency (10)
# --------------------------------------------------------------------------
def efficiency_of(c: Mapping[str, Any]) -> float:
    return clean(c["expectedReward"] / c["positionValue"])


def peer_efficiencies_for(own_efficiency: float, other_peer_efficiencies: Iterable[float]) -> list[float]:
    """Live-Queue peer set: the other contemporaneous competing candidates, plus itself.

    The CALLER must apply the v1.1 pool rules (candidateRanker.ts / liveQueue.ts):
    only candidates that are strategy-eligible with complete inputs, inside their
    own 10-minute alert window (now - alert < 10 min), not data-blocked, held or
    latched. The component is frozen at the first valid scoring and must not be
    recomputed as peers arrive or leave - freezing is the caller's state.
    """
    return [*other_peer_efficiencies, own_efficiency]


def score_capital_efficiency(c: Mapping[str, Any], peer_efficiencies: Sequence[float],
                             weights: Mapping[str, float] | None = None) -> dict[str, Any]:
    """peer_efficiencies INCLUDES the candidate's own efficiency."""
    if not _gt0(c.get("positionValue")):
        return _missing("capitalEfficiency", "position value", weights)
    if not is_num(c.get("expectedReward")):
        raise ValueError("expectedReward must be a finite number")
    eff = clean(c["expectedReward"] / c["positionValue"])
    n = len(peer_efficiencies)
    if n < MIN_CANDIDATES_FOR_RELATIVE:
        base, pct = 6, None
    else:
        less = sum(1 for x in peer_efficiencies if x < eff - 1e-12)
        equal = sum(1 for x in peer_efficiencies if abs(x - eff) <= 1e-12)
        pct = (less + 0.5 * (equal - 1)) / (n - 1)
        base = int(js_round(2 + 8 * pct))
    return _make("capitalEfficiency", base, weights=weights,
                 detail={"efficiency": eff, "peerCount": n, "percentile": pct,
                         "method": "NEUTRAL" if pct is None else "PERCENTILE"})


# --------------------------------------------------------------------------
# 8. Capacity / capital availability (8)
# --------------------------------------------------------------------------
def score_capital_availability(c: Mapping[str, Any], pf: Mapping[str, Any],
                               weights: Mapping[str, float] | None = None) -> dict[str, Any]:
    _require_plan(c)
    fit = check_fit(_as_classified(c), pf)
    used = c["positionValue"] / pf["available"] if pf["available"] > 0 else math.inf
    fits = fit["capitalOk"] and fit["slotOk"] and fit["sizeOk"]
    base = 0 if not fits else 8 if used <= 0.5 else 5 if used <= 0.8 else 2
    return _make("capitalAvailability", base, weights=weights, detail={
        "used": used, "fits": fits, "slotOk": fit["slotOk"],
        "capitalOk": fit["capitalOk"], "sizeOk": fit["sizeOk"]})


# --------------------------------------------------------------------------
# 9. Correlation (7)
# --------------------------------------------------------------------------
def score_correlation(c: Mapping[str, Any], pf: Mapping[str, Any],
                      weights: Mapping[str, float] | None = None) -> dict[str, Any]:
    if not _text(_inputs(c).get("sector")).strip():
        return _missing("correlation", "sector", weights)
    a = assess_correlation(_as_classified(c), pf["exposures"])
    return _make("correlation", a["basePoints"], weights=weights, detail=a)


# --------------------------------------------------------------------------
# 10. Portfolio risk (5)
# --------------------------------------------------------------------------
def score_portfolio_risk(c: Mapping[str, Any], pf: Mapping[str, Any],
                         weights: Mapping[str, float] | None = None) -> dict[str, Any]:
    _require_plan(c)
    projected = clean(pf["heatCommitted"] + c["plannedRisk"])
    ratio = projected / pf["heatLimit"] if pf["heatLimit"] > 0 else math.inf
    base = (0 if ratio > 1 + 1e-9 else 5 if ratio <= 0.5 else 4 if ratio <= 0.75
            else 3 if ratio <= 0.9 else 2)
    return _make("portfolioRisk", base, weights=weights,
                 detail={"projectedHeat": projected, "heatLimit": pf["heatLimit"], "ratio": ratio})


def _require_plan(c: Mapping[str, Any]) -> None:
    # The original always has a numeric trade plan here (no plan -> no candidate).
    if not (is_num(c.get("positionValue")) and is_num(c.get("plannedRisk"))):
        raise ValueError("positionValue and plannedRisk must be finite numbers (trade plan required)")


# --------------------------------------------------------------------------
# Completeness, tiers, totals
# --------------------------------------------------------------------------
def missing_inputs(c: Mapping[str, Any]) -> list[str]:
    """candidateRanker.ts missingInputs: every listed value must be a finite number > 0."""
    i = _inputs(c)
    out = []
    for key, name in (("rvol", "RVOL(20)"), ("rsi", "RSI(14)"), ("vwap", "VWAP"),
                      ("ema9", "EMA9"), ("ema20", "EMA20"),
                      ("close15m", "Last completed 15m Close"),
                      ("ema20_15m", "Last completed 15m EMA20")):
        if not _gt0(i.get(key)):
            out.append(name)
    if not _text(i.get("sector")).strip():
        out.append("Sector")
    if not _gt0(c.get("atr")):
        out.append("ATR")
    if not _gt0(c.get("positionValue")):
        out.append("Position value")
    return out


def classify_score(total: float) -> str:
    if total >= GRADES["elite"]:
        return "ELITE"
    if total >= GRADES["high"]:
        return "HIGH_PRIORITY"
    if total >= GRADES["watchlist"]:
        return "WATCHLIST"
    if total >= GRADES["low"]:
        return "LOW_PRIORITY"
    return "SKIP"


def meets_min_trade_score(total: float | None) -> bool:
    """Score >= 85 (tier ELITE or HIGH_PRIORITY). Necessary, never sufficient."""
    return total is not None and math.isfinite(total) and total >= MIN_TRADE_SCORE


def score_components(c: Mapping[str, Any], pf: Mapping[str, Any],
                     peer_efficiencies: Sequence[float],
                     weights: Mapping[str, float] | None = None) -> list[dict[str, Any]]:
    return [
        score_trend(c, weights), score_rvol(c, weights), score_momentum(c, weights),
        score_candle(c, weights), score_location(c, weights), score_time(c, weights),
        score_capital_efficiency(c, peer_efficiencies, weights),
        score_capital_availability(c, pf, weights),
        score_correlation(c, pf, weights),
        score_portfolio_risk(c, pf, weights),
    ]


def apply_hard_fail_na(components: list[dict[str, Any]],
                       strategy_fail_codes: Iterable[str]) -> list[dict[str, Any]]:
    na_keys = {HARD_FAIL_NA[code] for code in strategy_fail_codes if code in HARD_FAIL_NA}
    return [{**k, "points": 0, "na": True} if k["key"] in na_keys else k for k in components]


def score_opportunity(c: Mapping[str, Any], pf: Mapping[str, Any],
                      peer_efficiencies: Sequence[float], *,
                      strategy_fail_codes: Iterable[str] = (),
                      weights: Mapping[str, float] | None = None) -> dict[str, Any]:
    """Full v1.1 score for one candidate.

    c  : direction, ticker, atr (5m ATR14 of the signal candle), currentPrice
         (price at evaluation, NOT the signal close), open/high/low/close of the
         signal candle, alertTime "HH:MM" ET, chaseDistanceAtr (optional),
         positionValue, plannedRisk, expectedReward (from trade construction),
         inputs{rvol, rsi, vwap, ema9, ema20, close15m, ema20_15m, sector,
         industry, theme}.
    pf : build_portfolio(...) state WITHOUT this candidate.
    peer_efficiencies : see peer_efficiencies_for() - includes this candidate.
    strategy_fail_codes : codes produced by the SEPARATE strategy hard-rule
         layer. Any code (or any missing input) means total/setup/fit/tier are
         None: the candidate is not scored and cannot be ranked.
    """
    fails = list(strategy_fail_codes)
    components = apply_hard_fail_na(score_components(c, pf, peer_efficiencies, weights), fails)
    missing = missing_inputs(c)
    can_score = not fails and not missing

    def sum_keys(keys: Sequence[str]) -> float:
        acc = 0.0
        for k in components:  # same left-to-right order as the original reduce
            if k["key"] in keys:
                acc = acc + k["points"]
        return round1(acc)

    setup = min(SETUP_CAP, sum_keys(SETUP_KEYS)) if can_score else None
    fit = min(FIT_CAP, sum_keys(FIT_KEYS)) if can_score else None
    total = min(TOTAL_CAP, round1(setup + fit)) if can_score else None
    tier = classify_score(total) if total is not None else None
    return {
        "components": {k["key"]: k["points"] for k in components},
        "componentDetail": components,
        "setup": setup, "fit": fit, "total": total, "tier": tier,
        "missing": missing, "complete": not missing,
        "strategyFailCodes": fails,
        "scoringStatus": ("NOT ELIGIBLE - CANNOT BE RANKED" if fails
                          else "SCORING INCOMPLETE" if missing else "SCORED"),
        "meetsMinTradeScore": meets_min_trade_score(total),
        "minTradeScore": MIN_TRADE_SCORE,
        "authorization": AUTHORIZATION,
    }
