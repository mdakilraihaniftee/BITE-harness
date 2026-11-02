# Task V semantic incremental value

Status: **NOT ESTIMATED. No semantic observations exist.**

## Question

Does semantic evidence improve prediction of original-candidate correctness
beyond the SAM 3 score (*D_semantic* = Brier(MS) − Brier(M0) < 0)? And is it
complementary to the archived Zoom evidence? The complementarity contrasts are
MZS − MS, MZS − MZ and MS − MZ, and they are exploratory.

## Interpretation rules (fixed before data)

- Adding features to a fitted model is not evidence of extra information. Only
  out-of-fold paired differences count, and their group-bootstrap intervals
  must be reported alongside them.
- An interval that crosses zero is reported as unresolved. It does not justify a
  larger collection by itself.
- The semantic and SAM 3 observations share the image and the proposal. MZS is
  a joint discriminative model, not a product of independent likelihoods.
- Exploratory interpretation needs effects that do not depend on one group. The
  guard overlay downgrades `PROCEED` to `INCONCLUSIVE` in either of these cases:
  - removing a single group makes the semantic Brier gain zero or negative;
  - an endpoint has positives in fewer than 3 groups.

  The overlay was written down in Phase 4C-1F before any data existed.
- A fitted model's probability movement is not an upper bound on achievable
  gain. See the correction in `BITE_DEPENDENT_EVIDENCE_VALUE_THEORY.md` §3.
- The movement plus cross-term decomposition
  (`action_utility_screen.squared_loss_identity_diagnostic`) may be reported for
  MS − M0 descriptively, once data exist.

## Population caveat

Seven-class querying makes class-absent negatives dominate. A semantic benefit
that mostly comes from recognizing background or unrelated objects in
annotation-negative regions is a valid result *for this controlled benchmark*.
Whether it carries over to naturally selected agent queries remains unknown.
