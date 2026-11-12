# QUICK GUIDE

1. Read the routing rule below and the 20 labelled questions in
   [tier2-calibration.json](tier2-calibration.json) (10 per tier).
2. re-run this set when you change the classifier, the question or the threshold.

## Tier 2 routing rule

Is this a request that needs careful multi-step reasoning, such as a rigorous proof or hard maths, complex code, debugging or architecture design, or a deep expert analysis or comparison with trade-offs, rather than a fact, short writing, a translation, a summary or an everyday question?

The question is the `HA_ROUTE_TIER_QUESTION` setting, with no question text
built into the code. `HA_ROUTE_TIER_THRESHOLD` is **0.5**; scores at or above
it suggest tier 2. Fixed rights checks still decide which tier may answer.

Aziz supplied these calibration results from **12 Nov 2026**, with **two runs
per classifier** of the same 20 labelled questions:

| Classifier | Tier 1 scores | Tier 2 scores |
|---|---|---|
| Jev | 0.02–0.04 | 0.78–0.98 |
| DeepSeek | 0.00–0.02 | 0.93–1.00 |

The 0.5 threshold sits in the middle of the observed gap between the tier 1
and tier 2 scores. The calibration file is copied unchanged from the supplied
labelled set.
