"""OPTIONAL differential test: original RB v1.1 JavaScript scorer vs the Python port.

Runs only when invoked explicitly (the file name is deliberately not test_*.py,
so pytest does not collect it). From the project root:

    python tests/differential/run_differential.py --count 2000     # smoke
    python tests/differential/run_differential.py                  # full (60,000 random)
    python tests/differential/run_differential.py --mutation-check # sensitivity self-test

What it does
  1. Verifies reference/RB_v1.1_parity/code/golden.mjs against the SHA-256 in
     the audit manifest. Refuses to run on a mismatch.
  2. Copies the engine part of that file (the original RB functions, without the
     fixture-writing harness) plus js_driver.mjs into a TEMPORARY directory.
     Nothing is written inside the repository or the reference folder.
  3. Generates deterministic inputs (fixed seeds), scores them with Node using
     the ORIGINAL functions and with scoring/opportunity_scorer.py, and compares
     components, missing flags, missing-input list, setup, fit, total, tier,
     candle metrics and portfolio state with exact equality (no tolerance).

The two sides run independently: the JavaScript side contains no Python-derived
logic and this file contains no scoring logic.

SCOPE: scoring-formula parity only. It does NOT validate trade authorization,
hard-rule evaluation, broker reconciliation, portfolio allocation, peer-pool
selection/freezing, market-data parity or IBKR execution. See README.md.

Exit codes: 0 all equal; 1 mismatch / coverage gap / mutation not detected;
2 prerequisite missing (Node.js, reference file, manifest hash).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from scoring import opportunity_scorer as S  # noqa: E402  production implementation

REF = ROOT / "reference" / "RB_v1.1_parity"
GOLDEN_MJS = REF / "code" / "golden.mjs"
MANIFEST = REF / "out" / "NT_AUDIT_MANIFEST.txt"
JS_DRIVER = HERE / "js_driver.mjs"

DEFAULT_SEED = 20261109      # seed of the original Phase 3A 60,000-case run
DEFAULT_COUNT = 60000
COVERAGE_ENFORCED_FROM = 20000  # below this, coverage gaps are reported, not failed

ENGINE_START_MARKER = "ranker/candidateRanker.ts"  # last engine file the scorer needs
NA_CODES = ("AFTER_HOURS", "OUTSIDE_ENTRY_WINDOW", "INVALID_CANDLE_DIRECTION",
            "HTF_CONFIRMATION_FAILED", "CHASED_SETUP")
OTHER_FAIL_CODES = ("EXISTING_SAME_TICKER_POSITION", "RISK_LIMIT", "INVALID_TRADE_STRUCTURE")

SECTORS = [("Technology", "Software", ""), ("Technology", "Cyber", ""), ("Technology", "", "AI"),
           ("Energy", "Oil", ""), ("Health", "Pharma", "AI"), ("", "", ""), ("Utilities", "Electric", "")]
TICKERS = ["AAA", "BBB", "CCC", "DDD", "EEE"]
RVOL_GRID = [0, 1.2, 1.4999, 1.5, 1.9999, 2, 2.4999, 2.5, 3.4999, 3.5, 7]
RSI_GRID = [0, 25, 30, 35, 40, 45, 45.01, 54.99, 55, 59.99, 60, 65, 69.99, 70, 74.99, 75, 100]
TIME_GRID = ["09:30", "09:44", "09:45", "10:00", "11:29", "11:30", "13:59", "14:00", "15:29", "15:30",
             "16:00", "10:00:01", None]
CHASE_GRID = [0, None, -0.2, 0.0625, 0.125, 0.1875, 0.25, 0.3, 0.5, 1.3]

BASE = {
    "LONG": {"ticker": "AAA", "direction": "LONG", "atr": 0.4, "currentPrice": 99.95,
             "open": 99.7, "high": 100, "low": 99.6, "close": 99.98, "alertTime": "10:00",
             "chaseDistanceAtr": 0, "positionValue": 19903.98, "plannedRisk": 83.58, "expectedReward": 167.16,
             "inputs": {"rvol": 2.6, "rsi": 62, "vwap": 99.7, "ema9": 99.85, "ema20": 99.65, "close15m": 99.9,
                        "ema20_15m": 99.5, "sector": "Technology", "industry": "Software", "theme": ""}},
    "SHORT": {"ticker": "AAA", "direction": "SHORT", "atr": 0.4, "currentPrice": 100.05,
              "open": 100.3, "high": 100.4, "low": 100.0, "close": 100.02, "alertTime": "10:00",
              "chaseDistanceAtr": 0, "positionValue": 19996.0, "plannedRisk": 84.0, "expectedReward": 168.0,
              "inputs": {"rvol": 2.6, "rsi": 38, "vwap": 100.3, "ema9": 100.15, "ema20": 100.35, "close15m": 100.1,
                         "ema20_15m": 100.5, "sector": "Technology", "industry": "Software", "theme": ""}},
}


# ---------------------------------------------------------------------------
# Input generation (inputs only - no expected values are computed here)
# ---------------------------------------------------------------------------
def _cand(direction, over=None, inputs=None):
    b = BASE[direction]
    return {**b, **(over or {}), "inputs": {**b["inputs"], **(inputs or {})}}


def _pos(i, ticker, value, risk, sector, industry="", theme="", direction="LONG", pending=False):
    return {"id": f"p{i}", "ticker": ticker, "direction": direction, "sector": sector, "industry": industry,
            "theme": theme, "positionValue": value, "plannedRisk": risk, "status": "OPEN", "pending": pending}


def _case(tag, c, positions=(), peers=None, fails=()):
    pv = c["positionValue"]
    own = S.clean(c["expectedReward"] / pv) if isinstance(pv, (int, float)) and pv > 0 else 0.0
    return {"tag": tag, "c": c, "positions": list(positions),
            "peers": list(peers) if peers is not None else [own], "fails": list(fails)}


def boundary_cases():
    """Systematic one-factor-at-a-time cases on every documented threshold, LONG and SHORT."""
    out = []
    for d in ("LONG", "SHORT"):
        sgn = 1 if d == "LONG" else -1
        b = BASE[d]
        atr, e20, e15 = b["atr"], b["inputs"]["ema20"], b["inputs"]["ema20_15m"]
        for r in RVOL_GRID + [None]:
            out.append(_case(f"B-{d}-rvol", _cand(d, inputs={"rvol": r})))
        for r in RSI_GRID + [50, 64.99, None]:
            out.append(_case(f"B-{d}-rsi", _cand(d, inputs={"rsi": r})))
        for t in TIME_GRID:
            out.append(_case(f"B-{d}-time", _cand(d, {"alertTime": t})))
        for ch in CHASE_GRID:
            out.append(_case(f"B-{d}-chase", _cand(d, {"chaseDistanceAtr": ch})))
        for k in (-0.5, -0.01, 0, 0.01, 0.1, 0.24, 0.25, 0.5, 0.74, 0.75, 1.0, 1.01, 1.5, 1.51, 2.0, 2.01,
                  2.5, 2.51, 3.5, 3.51, 5):
            price = round(e20 + sgn * k * atr, 4)
            out.append(_case(f"B-{d}-price-vs-ema20", _cand(d, {"currentPrice": price})))
            out.append(_case(f"B-{d}-price-far-ema9", _cand(d, {"currentPrice": price},
                                                            {"ema9": round(price + sgn * 0.2, 4)})))
        for k in (-0.1, 0, 0.05, 0.09, 0.1, 0.24, 0.25, 0.49, 0.5, 0.6):
            out.append(_case(f"B-{d}-ema-sep", _cand(d, inputs={"ema9": round(e20 + sgn * k * atr, 4)})))
        for k in (-0.1, 0, 0.1, 0.24, 0.25, 0.5, 0.74, 0.75, 1.0):
            out.append(_case(f"B-{d}-15m", _cand(d, inputs={"close15m": round(e15 + sgn * k * atr, 4)})))
        for key in ("vwap", "ema9", "ema20", "close15m", "ema20_15m"):
            out.append(_case(f"B-{d}-missing-{key}", _cand(d, inputs={key: None})))
            out.append(_case(f"B-{d}-zero-{key}", _cand(d, inputs={key: 0})))
        for atr_v in (None, 0, -0.4):
            out.append(_case(f"B-{d}-atr", _cand(d, {"atr": atr_v})))
        for sector in ("", "   "):
            out.append(_case(f"B-{d}-sector-missing", _cand(d, inputs={"sector": sector})))
        # Candle shapes (O, H, L, C)
        for o, h, l, c in ((99.7, 100, 99.6, 99.98), (99.62, 100, 99.6, 100), (99.7, 100, 99.6, 99.75),
                           (99.7, 100, 99.6, 99.7), (99.6, 100, 99.58, 99.79), (99.72, 100, 99.6, 99.92),
                           (100, 100, 99.6, 100), (99.98, 100, 99.6, 99.7), (50, 50, 50, 50),
                           (100.3, 100.4, 100.0, 100.02), (100.3, 100.4, 100.0, 100.25), (100.0, 100.4, 100.0, 100.0),
                           (99.6, 100, 99.6, 100), (100, 100, 99.6, 99.6), (99.8, 100, 99.6, 99.81)):
            out.append(_case(f"B-{d}-candle", _cand(d, {"open": o, "high": h, "low": l, "close": c})))
        # Capacity: usage 0.5 / 0.8 boundaries, slots, size, pending reservations
        pv = b["positionValue"]
        for deployed in (0, round(80000 - 2 * pv, 2), round(80000 - 2 * pv + 0.01, 2), round(80000 - pv / 0.8, 2),
                         round(80000 - pv / 0.8 + 0.01, 2), round(80000 - pv, 2), round(80000 - pv + 0.01, 2), 80000, 90000):
            out.append(_case(f"B-{d}-capacity", _cand(d), [_pos(0, "CCC", deployed, 10, "Energy", "Oil")]))
            out.append(_case(f"B-{d}-capacity-pending", _cand(d), [_pos(0, "CCC", deployed, 10, "Energy", "Oil", pending=True)]))
        for n in (3, 4, 5):
            out.append(_case(f"B-{d}-slots", _cand(d), [_pos(i, f"X{i}", 1000, 10, f"S{i}", f"I{i}", pending=i % 2 == 0)
                                                         for i in range(n)]))
        for size in (0, 19999.99, 20000, 20000.01, 25000):
            out.append(_case(f"B-{d}-size", _cand(d, {"positionValue": size})))
        # Portfolio risk: heat ratio 0.50 / 0.75 / 0.90 / 1.00 boundaries
        risk = b["plannedRisk"]
        for target in (500, 750, 900, 1000):
            for eps in (-0.01, 0, 0.01):
                committed = round(target - risk + eps, 2)
                out.append(_case(f"B-{d}-heat", _cand(d), [_pos(0, "CCC", 1000, committed, "Energy", "Oil")]))
                out.append(_case(f"B-{d}-heat-split", _cand(d), [_pos(0, "CCC", 1000, round(committed / 2, 2), "Energy", "Oil"),
                                                                  _pos(1, "DDD", 1000, round(committed - round(committed / 2, 2), 2),
                                                                       "Health", "Pharma", pending=True)]))
        # Correlation: ticker / industry / theme / sector / none, either direction, normalisation
        for other_dir in ("LONG", "SHORT"):
            for p in (_pos(0, "aaa", 1000, 10, "Other", "Other", direction=other_dir),
                      _pos(0, "BBB", 1000, 10, "Technology", "Software", direction=other_dir),
                      _pos(0, "BBB", 1000, 10, "TECHNOLOGY", " software ", direction=other_dir),
                      _pos(0, "BBB", 1000, 10, "Technology", "Cyber", direction=other_dir),
                      _pos(0, "BBB", 1000, 10, " technology", "", direction=other_dir),
                      _pos(0, "BBB", 1000, 10, "Energy", "Oil", direction=other_dir),
                      _pos(0, "BBB", 1000, 10, "Energy", "Oil", "AI", direction=other_dir),
                      _pos(0, "BBB", 1000, 10, "", "", "", direction=other_dir)):
                out.append(_case(f"B-{d}-corr", _cand(d), [p]))
                out.append(_case(f"B-{d}-corr-theme", _cand(d, inputs={"theme": "ai", "industry": ""}), [p]))
                out.append(_case(f"B-{d}-corr-pending", _cand(d), [{**p, "pending": True}]))
        # Capital efficiency: neutral below 3 peers, percentile, ties, x.5 rounding
        own = S.clean(b["expectedReward"] / pv)
        lo, hi = round(own / 2, 8), round(own * 2, 8)
        for peers in ([own], [lo, own], [lo, hi, own], [hi, hi, own], [lo, lo, own], [own, own, own],
                      [lo, own, own], [hi, own, own], [lo, lo, hi, own], [lo, hi, hi, own],
                      [own] + [hi] * 7 + [own], [lo] + [hi] * 6 + [own, own], [lo] * 8 + [own],
                      [own + 1e-12, own - 1e-12, own], [own + 2e-12, own - 2e-12, own], []):
            out.append(_case(f"B-{d}-peers", _cand(d), peers=peers))
        out.append(_case(f"B-{d}-pv0", _cand(d, {"positionValue": 0})))
        # Strategy hard-fail codes -> N/A component, no total
        for code in NA_CODES + OTHER_FAIL_CODES:
            out.append(_case(f"B-{d}-fail-{code}", _cand(d), fails=[code]))
        out.append(_case(f"B-{d}-fail-many", _cand(d), fails=list(NA_CODES)))
        out.append(_case(f"B-{d}-fail+missing", _cand(d, inputs={"rsi": None}), fails=["CHASED_SETUP"]))
    return out


def random_cases(count, seed):
    """Unstructured stream. Draw order is identical to the original Phase 3A run
    (seed 20261109), so --count 60000 reproduces the same 60,000 candidates."""
    rnd = random.Random(seed)
    rnd_fail = random.Random(seed + 1)  # separate stream: does not disturb the draws above

    def px(base, spread):
        return round(base + rnd.randint(-spread, spread) * 0.01, 2)

    def maybe(v, p=0.03):
        return None if rnd.random() < p else v

    out = []
    for _ in range(count):
        d = rnd.choice(["LONG", "SHORT"])
        base = rnd.choice([0.95, 5, 20, 50, 100, 250])
        atr = rnd.choice([0.05, 0.1, 0.2, 0.25, 0.4, 0.5, 0.8, 1.0, 0.3333])
        lo = px(base, 30)
        hi = round(lo + rnd.randint(0, 60) * 0.01, 2)
        o = round(lo + rnd.randint(0, int(round((hi - lo) * 100))) * 0.01, 2)
        cl = round(lo + rnd.randint(0, int(round((hi - lo) * 100))) * 0.01, 2)
        sec = rnd.choice(SECTORS)
        pv = rnd.choice([0, 500, 5000, 12000, 19903.98, 20000, 20000.01, 25000, 40000])
        c = {"ticker": rnd.choice(TICKERS), "direction": d, "atr": maybe(atr, 0.02), "currentPrice": px(base, 150),
             "open": o, "high": hi, "low": lo, "close": cl,
             "alertTime": rnd.choice(TIME_GRID),
             "chaseDistanceAtr": rnd.choice(CHASE_GRID + [round(rnd.random(), 4)]),
             "positionValue": pv, "plannedRisk": rnd.choice([0, 10, 83.58, 125, 250, 400]),
             "expectedReward": rnd.choice([0, 20, 100, 167.16, 200, 500]),
             "inputs": {"rvol": maybe(rnd.choice(RVOL_GRID + [round(rnd.random() * 5, 3)])),
                        "rsi": maybe(rnd.choice(RSI_GRID + [round(rnd.random() * 100, 2)])),
                        "vwap": maybe(px(base, 150)), "ema9": maybe(px(base, 150)), "ema20": maybe(px(base, 150)),
                        "close15m": maybe(px(base, 150)), "ema20_15m": maybe(px(base, 150)),
                        "sector": sec[0], "industry": sec[1], "theme": sec[2]}}
        positions = []
        for j in range(rnd.choice([0, 0, 1, 2, 3, 4, 5])):
            s = rnd.choice(SECTORS)
            positions.append({"id": f"p{j}", "ticker": rnd.choice(TICKERS + ["ZZZ", "YYY"]),
                              "direction": rnd.choice(["LONG", "SHORT"]),
                              "sector": rnd.choice([s[0], s[0].upper(), " " + s[0]]), "industry": s[1], "theme": s[2],
                              "positionValue": rnd.choice([500, 5000, 20000, 30000, 40096.02, 60096.02, 65000]),
                              "plannedRisk": rnd.choice([10, 50, 250, 416.42, 500, 666.42, 816.42, 916.42, 950]),
                              "status": "OPEN", "pending": rnd.random() < 0.3})
        own = S.clean(c["expectedReward"] / pv) if pv > 0 else 0.0
        pool = [0.0, 0.001, 0.005, 0.0084, 0.01, 0.025, own, own]
        peers = [rnd.choice(pool) for _ in range(rnd.choice([0, 1, 2, 3, 4, 8, 9]))] + [own]
        fails = [rnd_fail.choice(NA_CODES + OTHER_FAIL_CODES)] if rnd_fail.random() < 0.08 else []
        out.append({"tag": "RANDOM", "c": c, "positions": positions, "peers": peers, "fails": fails})
    return out


def aligned_cases(count, seed):
    """Well-formed setups (the unstructured stream almost never aligns every input,
    so on its own it would under-sample high scores and the ELITE/HIGH tiers)."""
    rnd = random.Random(seed + 2)
    out = []
    for _ in range(count):
        d = rnd.choice(["LONG", "SHORT"])
        sgn = 1 if d == "LONG" else -1
        b = BASE[d]
        rsi = rnd.choice([55, 57, 60, 62, 65, 67, 69.99, 70, 72, 75, 80])
        c = _cand(d, {"alertTime": rnd.choice(["09:45", "10:00", "11:29", "11:30", "12:00", "14:00", "15:29"]),
                      "currentPrice": round(b["currentPrice"] + sgn * rnd.choice([-0.2, -0.1, 0, 0, 0, 0.05, 0.1, 0.3]), 2),
                      "chaseDistanceAtr": rnd.choice([0, 0, 0, None, -0.175, 0.0625, 0.125, 0.25])},
                  {"rvol": rnd.choice([1.5, 1.6, 2.0, 2.1, 2.5, 2.6, 3.5, 3.6]),
                   "rsi": rsi if d == "LONG" else round(100 - rsi, 2)})
        if rnd.random() < 0.4:  # strong breakout candle
            c.update({"open": 99.62, "close": 100.0} if d == "LONG" else {"open": 100.38, "close": 100.0})
        positions = []
        for j in range(rnd.choice([0, 0, 0, 1, 1, 2, 3])):
            sec = rnd.choice([("Energy", "Oil", ""), ("Health", "Pharma", ""), ("Technology", "Cyber", ""),
                              ("Utilities", "Electric", ""), ("Technology", "Software", "")])
            positions.append(_pos(j, rnd.choice(["CCC", "DDD", "EEE", "ZZZ"]), rnd.choice([500, 5000, 20000, 40000]),
                                  rnd.choice([10, 50, 250, 416.42, 666.42, 816.42]), *sec,
                                  direction=rnd.choice(["LONG", "SHORT"]), pending=rnd.random() < 0.3))
        own = S.clean(c["expectedReward"] / c["positionValue"])
        pool = [round(own / 2, 8), own, own, round(own * 1.5, 8), 0.005, 0.01]
        peers = [rnd.choice(pool) for _ in range(rnd.choice([0, 0, 1, 2, 3, 5]))] + [own]
        out.append({"tag": "ALIGNED", "c": c, "positions": positions, "peers": peers, "fails": []})
    return out


# ---------------------------------------------------------------------------
# The two independent sides
# ---------------------------------------------------------------------------
def python_result(k):
    pf = S.build_portfolio([{**p, "kind": "PENDING" if p["pending"] else "POSITION"}
                            for p in k["positions"] if p["status"] == "OPEN"])
    r = S.score_opportunity(k["c"], pf, k["peers"], strategy_fail_codes=k["fails"])
    return {"components": r["components"],
            "missingFlags": {x["key"]: x["missing"] for x in r["componentDetail"]},
            "missing": r["missing"], "setup": r["setup"], "fit": r["fit"], "total": r["total"], "tier": r["tier"],
            "candle": S.candle_metrics(k["c"]),
            "portfolio": {"available": pf["available"], "slotsUsed": pf["slotsUsed"],
                          "heatCommitted": pf["heatCommitted"]}}


def verify_reference():
    for path in (GOLDEN_MJS, MANIFEST, JS_DRIVER):
        if not path.exists():
            print(f"PREREQUISITE MISSING: {path}")
            raise SystemExit(2)
    digest = hashlib.sha256(GOLDEN_MJS.read_bytes()).hexdigest()
    expected = None
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*").replace("\\", "/") == "code/golden.mjs":
            expected = parts[0].lower()
    if expected is None:
        print("PREREQUISITE MISSING: no code/golden.mjs entry in the audit manifest")
        raise SystemExit(2)
    ok = digest == expected
    print(f"JS reference : {GOLDEN_MJS.relative_to(ROOT)}")
    print(f"  sha256     : {digest}")
    print(f"  manifest   : {expected}  -> {'MATCH' if ok else 'MISMATCH - refusing to run'}")
    if not ok:
        raise SystemExit(2)
    return digest


def engine_source():
    """Original engine functions only: everything before the first source file that
    follows ranker/candidateRanker.ts. The fixture-writing harness at the end of
    golden.mjs is NOT included, so the golden fixtures cannot be regenerated."""
    lines = GOLDEN_MJS.read_text(encoding="utf-8").splitlines(keepends=True)
    start = next((i for i, ln in enumerate(lines) if ln.startswith("// ") and ENGINE_START_MARKER in ln), None)
    if start is None:
        print("PREREQUISITE MISSING: candidateRanker.ts section not found in golden.mjs")
        raise SystemExit(2)
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("// ../")), None)
    if end is None:
        print("PREREQUISITE MISSING: end of candidateRanker.ts section not found in golden.mjs")
        raise SystemExit(2)
    return "".join(lines[:end])


def run_js(cases, workdir: Path, engine_text: str, name="engine"):
    node = shutil.which("node")
    if not node:
        print("PREREQUISITE MISSING: Node.js ('node') was not found on PATH. Install Node.js yourself "
              "(nothing is installed automatically) and re-run.")
        raise SystemExit(2)
    script, cases_file, out_file = workdir / f"{name}.mjs", workdir / "cases.json", workdir / f"{name}_out.json"
    script.write_text(engine_text + JS_DRIVER.read_text(encoding="utf-8"), encoding="utf-8")
    if not cases_file.exists():
        cases_file.write_text(json.dumps([{k: v for k, v in c.items() if k != "tag"} for c in cases],
                                         allow_nan=False), encoding="utf-8")
    proc = subprocess.run([node, str(script), str(cases_file), str(out_file)], capture_output=True, text=True)
    if proc.returncode != 0:
        print("JavaScript reference failed to run:\n" + proc.stderr[-2000:])
        raise SystemExit(1)
    return json.loads(out_file.read_text(encoding="utf-8"))


def compare(cases, js_results, verbose=True):
    """Exact equality on every compared field. Returns (mismatch_count, coverage)."""
    mismatches, first = 0, None
    cov = {"direction": set(), "tier": set(), "missingFlag": set(), "naZeroed": set(), "tag": {}}
    for idx, (k, js) in enumerate(zip(cases, js_results)):
        try:
            py = python_result(k)
        except Exception as exc:  # a crash on the Python side is a mismatch, never a skip
            py = {"pythonException": repr(exc)}
        if py != js:
            mismatches += 1
            if first is None:
                first = (idx, k, py, js)
        cov["direction"].add(k["c"]["direction"])
        cov["tier"].add(js["tier"])
        cov["tag"][k["tag"].split("-")[0]] = cov["tag"].get(k["tag"].split("-")[0], 0) + 1
        for key, pts in js["components"].items():
            cov.setdefault(key, set()).add(pts)
        cov["missingFlag"].update(key for key, flag in js["missingFlags"].items() if flag)
        cov["naZeroed"].update(k["fails"])
    if first and verbose:
        idx, k, py, js = first
        fields = sorted(f for f in set(py) | set(js) if py.get(f) != js.get(f))
        print("\nFIRST MISMATCH (complete, reproducible)")
        print(f"  case index : {idx}   tag: {k['tag']}")
        print(f"  differing  : {fields}")
        print("  input      : " + json.dumps({x: k[x] for x in ("c", "positions", "peers", "fails")}))
        print("  python     : " + json.dumps(py))
        print("  javascript : " + json.dumps(js))
    return mismatches, cov


REQUIRED_COVERAGE = {
    "trend": set(range(16)), "rvol": {0, 6, 9, 12, 15}, "momentum": {0, 4, 6, 7, 9, 10},
    "candle": set(range(11)), "location": set(range(11)), "time": {0, 6, 8, 10},
    "capitalEfficiency": {0, 2, 3, 4, 5, 6, 7, 8, 9, 10}, "capitalAvailability": {0, 2, 5, 8},
    "correlation": {0, 4, 7}, "portfolioRisk": {0, 2, 3, 4, 5},
    "tier": {"ELITE", "HIGH_PRIORITY", "WATCHLIST", "LOW_PRIORITY", "SKIP", None},
    "direction": {"LONG", "SHORT"},
    "missingFlag": {"trend", "rvol", "momentum", "location", "time", "capitalEfficiency", "correlation"},
    "naZeroed": set(NA_CODES),
}


def coverage_gaps(cov):
    return {key: sorted(need - cov.get(key, set()), key=str) for key, need in REQUIRED_COVERAGE.items()
            if need - cov.get(key, set())}


def build_cases(count, seed):
    return boundary_cases() + random_cases(count, seed) + aligned_cases(max(1, count // 10), seed)


# ---------------------------------------------------------------------------
def run(count, seed):
    started = time.perf_counter()
    verify_reference()
    cases = build_cases(count, seed)
    with tempfile.TemporaryDirectory(prefix="rb_v11_diff_") as tmp:
        js_results = run_js(cases, Path(tmp), engine_source())
    if len(js_results) != len(cases):
        print(f"JavaScript returned {len(js_results)} results for {len(cases)} cases")
        raise SystemExit(1)
    mismatches, cov = compare(cases, js_results)
    gaps = coverage_gaps(cov)
    elapsed = time.perf_counter() - started
    print("\n============ RB v1.1 SCORING DIFFERENTIAL (JS original vs Python port) ============")
    print(f"Seed                 : {seed}  (random stream; fail-code stream seed+1; aligned stream seed+2)")
    print(f"Cases                : {len(cases)}  {cov['tag']}")
    print(f"Passed               : {len(cases) - mismatches}")
    print(f"Mismatches           : {mismatches}")
    print(f"Execution time       : {elapsed:.1f} s")
    print("Compared (exact ==)  : 10 component points, 10 missing flags, missing-input list, setup, fit,")
    print("                       total, tier, 10 candle metrics, portfolio available/slots/heat")
    print("Original outputs seen: " + "; ".join(
        f"{key}={sorted(cov[key], key=lambda x: (x is None, str(x) if isinstance(x, str) else x))}"
        for key in ("trend", "rvol", "momentum", "candle", "location", "time", "capitalEfficiency",
                    "capitalAvailability", "correlation", "portfolioRisk", "tier")))
    enforce = count >= COVERAGE_ENFORCED_FROM
    if gaps:
        print(f"Coverage gaps        : {gaps}" + ("" if enforce else "  (informational at this count)"))
    else:
        print("Coverage gaps        : none - every documented output value, tier, direction, missing flag and N/A code occurred")
    print("Scope                : scoring formulas only. NOT validated: trade authorization, hard rules,")
    print("                       broker reconciliation, allocation, peer-pool selection/freezing,")
    print("                       market-data parity, IBKR execution.")
    failed = mismatches > 0 or (enforce and bool(gaps))
    print("RESULT               : " + ("FAIL" if failed else "PASS"))
    return 1 if failed else 0


def mutation_check(count, seed):
    """Proves the comparison can fail. Nothing on disk is modified: the Python
    mutation is an in-process patch, the JavaScript mutation is applied to the
    temporary copy of the engine text only."""
    verify_reference()
    cases = build_cases(count, seed)
    engine = engine_source()
    js_mutations = (
        ("JS trend band: 'sep < 0.25 ? 3' -> '? 2'", "sep < 0.25 ? 3", "sep < 0.25 ? 2"),
        ("JS RVOL band: 2.5 -> 12 points changed to 11", "{ min: 2.5, points: 12,", "{ min: 2.5, points: 11,"),
    )
    py_mutations = (
        ("Python js_round replaced by banker's round()", "js_round", lambda x: float(round(x))),
        ("Python tier boundary: classify_score shifted by 0.1", "classify_score",
         (lambda orig: (lambda total: orig(total - 0.1)))(S.classify_score)),
    )
    results = []
    with tempfile.TemporaryDirectory(prefix="rb_v11_diff_mut_") as tmp:
        tmp = Path(tmp)
        baseline_js = run_js(cases, tmp, engine)
        baseline, _ = compare(cases, baseline_js, verbose=False)
        print(f"\nBaseline (no mutation): {baseline} mismatches in {len(cases)} cases")
        for n, (label, old, new) in enumerate(js_mutations):
            if engine.count(old) != 1:
                print(f"Mutation target not unique in the reference: {old!r}")
                raise SystemExit(1)
            found, _ = compare(cases, run_js(cases, tmp, engine.replace(old, new), name=f"mutant{n}"), verbose=False)
            results.append((label, found))
        for label, attr, replacement in py_mutations:
            with mock.patch.object(S, attr, replacement):
                found, _ = compare(cases, baseline_js, verbose=False)
            results.append((label, found))
        after, _ = compare(cases, baseline_js, verbose=False)
    print("\n============ MUTATION-SENSITIVITY CHECK ============")
    for label, found in results:
        print(f"{'DETECTED    ' if found else 'NOT DETECTED'} {label}: {found} mismatches")
    print(f"After removing mutations: {after} mismatches (production code unchanged)")
    ok = baseline == 0 and after == 0 and all(found > 0 for _, found in results)
    print("RESULT: " + ("PASS - every mutation was detected" if ok else "FAIL"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--count", type=int, default=DEFAULT_COUNT,
                    help=f"random cases (default {DEFAULT_COUNT}); boundary and aligned cases are added on top")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED, help=f"default {DEFAULT_SEED}")
    ap.add_argument("--mutation-check", action="store_true",
                    help="verify that deliberately wrong JS/Python variants are detected (uses --count, default 3000)")
    args = ap.parse_args()
    if args.count < 1:
        ap.error("--count must be >= 1")
    if args.mutation_check:
        raise SystemExit(mutation_check(args.count if args.count != DEFAULT_COUNT else 3000, args.seed))
    raise SystemExit(run(args.count, args.seed))


if __name__ == "__main__":
    main()
