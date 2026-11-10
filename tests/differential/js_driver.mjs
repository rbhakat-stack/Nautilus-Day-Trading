
// ---------------------------------------------------------------------------
// Differential driver. run_differential.py appends this text to a TEMPORARY copy
// of the audited engine source taken from reference/RB_v1.1_parity/code/golden.mjs
// (rounding.ts ... ranker/candidateRanker.ts). It is never run on its own and it
// contains NO scoring logic: every number below is produced by the original RB
// functions (buildPortfolio, scoreComponents, missingInputs, hardFailNA, applyNA,
// sumKeys, round12, classifyScore, candleMetrics).
// The totals block mirrors candidateRanker.ts rankCandidates ("scored" step).
// usage: node <temp engine+driver>.mjs <cases.json> <out.json>
// ---------------------------------------------------------------------------
import { readFileSync as __readFileSync } from "node:fs";
const __cases = JSON.parse(__readFileSync(process.argv[2], "utf8"));
const __results = __cases.map((k) => {
  const pf = buildPortfolio(k.positions, [], RANKER_DEFAULTS);
  const strategyFails = k.fails.map((code) => fail(code, "differential", HARD_FAIL_LABELS[code] ?? code));
  const comps = applyNA(scoreComponents(k.c, pf, k.peers, RANKER_DEFAULTS), hardFailNA(k.c, strategyFails));
  const miss = missingInputs(k.c);
  const canScore = !strategyFails.length && !miss.length;
  const setup = canScore ? Math.min(70, sumKeys(comps, SETUP_KEYS)) : null;
  const fit = canScore ? Math.min(30, sumKeys(comps, FIT_KEYS)) : null;
  const total = setup !== null && fit !== null ? Math.min(100, round12(setup + fit)) : null;
  return {
    components: Object.fromEntries(comps.map((x) => [x.key, x.points])),
    missingFlags: Object.fromEntries(comps.map((x) => [x.key, !!x.missing])),
    missing: miss,
    setup, fit, total,
    tier: total !== null ? classifyScore(total, RANKER_DEFAULTS) : null,
    candle: candleMetrics(k.c),
    portfolio: { available: pf.available, slotsUsed: pf.slotsUsed, heatCommitted: pf.heatCommitted },
  };
});
writeFileSync(process.argv[3], JSON.stringify(__results));
