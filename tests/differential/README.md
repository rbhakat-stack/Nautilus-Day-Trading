# RB v1.1 scoring differential test (optional)

Compares the **original RB v1.1 JavaScript scorer** with the Python port in
`scoring/opportunity_scorer.py` on deterministic generated inputs. It is a
read-only regression test for the scoring formulas.

It runs **only when you start it**. The script is not named `test_*.py`, so
pytest does not collect it, and nothing in the application imports it.

## Prerequisites

- The project virtual environment (Python standard library only; nothing to install).
- Node.js on `PATH` (developed with v24). If `node` is missing the script says so
  and exits with code 2. It never installs anything.
- `reference/RB_v1.1_parity/code/golden.mjs` and `reference/RB_v1.1_parity/out/NT_AUDIT_MANIFEST.txt`.

No network, no broker, no IBKR, no paid service.

## Commands (Windows PowerShell, from the project root)

Smoke test, about 2 seconds:

```powershell
.\.venv\Scripts\python.exe tests\differential\run_differential.py --count 2000
```

Complete test, 60,000 random cases plus boundary and aligned cases:

```powershell
.\.venv\Scripts\python.exe tests\differential\run_differential.py
```

Mutation-sensitivity self-test (proves the comparison can fail):

```powershell
.\.venv\Scripts\python.exe tests\differential\run_differential.py --mutation-check
```

Options: `--count N` (random cases), `--seed N` (default `20261109`).

Exit codes: `0` all equal; `1` mismatch, coverage gap, or an undetected mutation;
`2` missing prerequisite or manifest hash mismatch.

## How it works

1. **Reference check.** SHA-256 of `golden.mjs` must equal the entry in the audit
   manifest, otherwise the run is refused.
2. **JavaScript side.** The engine part of `golden.mjs` (the original functions up
   to and including `ranker/candidateRanker.ts`) is copied to a temporary directory
   and `js_driver.mjs` is appended. The driver only calls original functions
   (`buildPortfolio`, `scoreComponents`, `missingInputs`, `hardFailNA`, `applyNA`,
   `sumKeys`, `round12`, `classifyScore`, `candleMetrics`). The fixture-writing
   harness at the end of `golden.mjs` is not included, so the golden fixtures
   cannot be regenerated or overwritten. The temporary directory is deleted afterwards.
3. **Python side.** `build_portfolio`, `score_opportunity` and `candle_metrics`
   from the production module.
4. **Comparison.** Exact equality, no tolerance, on: 10 component points, 10
   missing flags, the missing-input list, setup, fit, total, tier, the candle
   metrics, and portfolio available / slots / committed heat. Both sides use
   IEEE-754 doubles; JavaScript `Math.round` runs natively on the JS side.
5. **On a mismatch** the first failing case is printed with its complete input,
   both outputs and the differing fields. A Python exception counts as a mismatch.

## Inputs

All inputs are synthetic. No market data and no sealed research data are used.

| Block | Count | Purpose |
|---|---|---|
| Boundary | 542 | One factor at a time on every documented threshold, LONG and SHORT: RVOL and RSI bands, time buckets, chase deduction, ATR distances for trend and location, candle shapes, capacity 0.5 / 0.8, slots, size, heat 0.50 / 0.75 / 0.90 / 1.00, correlation levels in either direction, peer ties, missing inputs, hard-fail N/A codes |
| Random | `--count` (default 60,000) | Unstructured stream, seed `20261109`. Same draw order as the original Phase 3A run, so the default reproduces those 60,000 candidates |
| Aligned | `--count` / 10 | Well-formed setups, seed + 2, so high scores and the ELITE / HIGH tiers occur |

Strategy fail codes for the random block come from a separate stream (seed + 1)
on about 8% of cases.

At 20,000 random cases or more the run also **fails on a coverage gap**: every
documented output value of every component, every tier, both directions, every
missing flag and every N/A code must have occurred in the original outputs.
Below that the gaps are printed as information only.

## Mutation check

`--mutation-check` runs four deliberately wrong variants and requires each to
produce mismatches:

- JavaScript trend band changed (temporary copy only)
- JavaScript RVOL band points changed (temporary copy only)
- Python `js_round` replaced by banker's `round()` (in-process patch)
- Python tier boundary shifted by 0.1 (in-process patch)

No file in the repository or the reference folder is modified. The check also
confirms 0 mismatches before and after the mutations.

## What this test does NOT validate

- Trade authorization (a score is never an authorization)
- Hard-rule evaluation: fail codes are fed in as inputs; the rules that produce them are not tested
- Broker reconciliation
- Portfolio allocation and ranking order
- Peer-pool selection and capital-efficiency freezing: the peer list is an input
- Market-data or indicator parity (SIP vs IBKR)
- IBKR execution behaviour
- Policy A/B and the v1.2 `QUALIFIED_FLOOR` RVOL path, which the Python port does not implement

## Limitations of the reference

- `golden.mjs` is the audit's esbuild bundle of RB commit `c3bbca4`. The audit
  verified the commit in git but did **not** re-verify the deployed bundle or the
  production flags. This test proves agreement with that bundle, nothing more.
- Only default settings are exercised (`RANKER_DEFAULTS`: default weights, 85
  minimum, $100,000 equity, 4 slots, 20% reserve, 1% heat).
- Candle OHLC and `currentPrice` are always finite numbers. The original has no
  missing-input branch for them; the Python port raises instead of scoring.
- NaN is never generated (JSON cannot carry it); missing values are `null` / `None`.
- Agreement on generated inputs is strong evidence, not a proof for all inputs.
