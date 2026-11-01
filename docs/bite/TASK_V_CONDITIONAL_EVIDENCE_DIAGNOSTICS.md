# Task V conditional-evidence diagnostics

Status: **descriptive only; no probability model fitted**. The extractor version
is `bite.focused_evidence_features.v1`. It constructs the runtime vector before
offline labels are joined and rejects inputs containing GT, official-TP, or
offline-association fields.

The vector records root-box IoU, normalized center displacement, log area
ratio, relative width/height change, crop-boundary indicators, original and
focused scores and censoring, score changes, proposal counts, association
category, detector-rank change, parent/crop/observation identities, backend,
query, transform validity, and cost. Root-frame mask overlap is `null` with an
explicit unavailable reason because an unambiguous mask transform was not
implemented. Missing values were not invented.

## Cohort-separated results at IoU 0.50

| Cohort / annotation label | Cases | Unique alignment | Ambiguous | No alignment | Median root IoU, aligned | Median score change, aligned |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Pilot positive | 4 | 4 | 0 | 0 | 0.9689 | 0.0273 |
| Pilot negative | 34 | 28 | 5 | 1 | 0.9699 | 0.0996 |
| Expansion positive | 31 | 29 | 2 | 0 | 0.9740 | 0.0117 |
| Expansion negative | 172 | 147 | 19 | 6 | 0.9681 | 0.0625 |

The overlap is substantial. In particular, a high-consistency focused proposal
is common for both annotation-positive and annotation-negative originals. This
is expected when the same SAM 3 backend is run on a crop derived from its own
proposal, and especially important when the queried class has no annotation.
Changed geometry is not evidence of positive information gain by itself.

Focused correctness and localization remain separate outcomes. In the pilot,
all four aligned positives remained positive, while 28 aligned negatives
remained annotation-negative; six negatives were ambiguous or unaligned. In
the expansion, 29 aligned positives remained positive, while 147 aligned
negatives remained annotation-negative; 25 cases were ambiguous or unaligned.
Same-target preservation was determinable for 4 pilot and 29 expansion positive
cases. Positive localization IoU change occurred in 3 and 20 respectively, but
that is an offline localization observation, not confirmation that Zoom verifies
arbitrary original candidates. One negative per cohort had a positive IoU
change without becoming a verified same target.

All-case summaries retain ambiguity and no-alignment as categories. The
aligned-only sensitivity tables are published separately and are not presented
as representative of all cases. There were no execution failures in these
completed focused branches. Analyses are clustered by source group; the pilot
and expansion remain separate because their query designs differ.

Conclusion: focused evidence is geometrically stable and produces different
proposal sets, but current development data do not establish useful conditional
separation beyond initial state. No significance, causal gain, information gain,
or held-out performance is claimed.

