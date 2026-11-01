# Phase 4B-2B-4 — annotation reliability and conditional evidence

Report date: **2026-11-01**. Status:
**ENGINEERING_SUCCESS / HUMAN_ADJUDICATION_PENDING**.

## Outcome

This phase implemented an offline, blind-first human adjudication workflow; a
GT-free focused-evidence extractor; cohort-separated paired diagnostics; an
action-space reassessment; an unfitted restricted Phase 4C model specification;
and a dimension-specific readiness gate. It performed no GPU/model inference,
model fitting, posterior update, planner work, checkpoint/data download, agent
decision change, or evaluator change.

Historical integrity was checked before analysis. The Phase 4B-2B-3 artifact
hashes, 40-state historical run, 210-state expansion run, and frozen source
manifest identity passed. Prior outputs were read, not rewritten.

## Review workflow

The versioned case set contains 241 candidates. Annotation and visual labels are
separate. Set A samples 25 candidate-bearing groups and 120 cases using seeded
cohort-stratified SRSWOR. Set B is a 228-case diagnostic union containing all 29
high-score invalid cases. Their union is 235. The interface was live-checked on
loopback: the HTML and `/api/cases` returned successfully. It verifies source
hashes before serving images and validates human records before exclusive
creation. Completed human judgments remain zero; no synthetic review exists.

## Evidence result

Runtime-only files contain 38 pilot and 203 expansion records and no GT label
fields. Ambiguous/no-alignment cases are retained (pilot 5/1; expansion 21/6).
Unique alignment is frequent for both labels: 4/4 versus 28/34 in the pilot and
29/31 versus 147/172 in expansion. Median aligned root IoU is approximately
0.97 in every cell. The richer evidence is valid, but separation is weak or
unestablished and no information-gain claim is made.

All 73 exact repeats remain deterministic controls under the observed service.
They are not independent evidence. Zoom-focus remains an experimental,
same-backend, derived-pixel observation costing two logical calls.

## Implementation

New offline modules:

- `evaluation_kit/bite_calibration/adjudication_schema.py`
- `evaluation_kit/bite_calibration/adjudication_sampling.py`
- `evaluation_kit/bite_calibration/adjudication_export.py`
- `evaluation_kit/bite_calibration/adjudication_validation.py`
- `evaluation_kit/bite_calibration/conditional_features.py`
- `evaluation_kit/bite_calibration/evidence_diagnostics.py`
- `evaluation_kit/bite_calibration/model_specification.py`
- `evaluation_kit/bite_calibration/statistical_readiness.py`

New entry points:

- `scripts/bite/build_task_v_review_queue.py`
- `scripts/bite/serve_task_v_review.py`
- `scripts/bite/validate_task_v_reviews.py`
- `scripts/bite/analyze_conditional_evidence.py`
- `scripts/bite/assess_phase4c_readiness.py`

The machine-readable root is `outputs/bite/phase04b2b4/`. It contains integrity,
review sampling/UI, pending human records, runtime features, paired diagnostics,
the model specification, readiness, validation, test, and manifest artifacts.

## Scientific decision

The annotation endpoint is reproducible but visually incomplete reliability is
unresolved. A compact prior-only experiment is ready with limitations. A pooled
Zoom model requires human review and grouped validation; general kernels, online
updating, end-to-end planning, and certificates are not ready. Phase 4C was not
started.

Source attribution: Aquarium Combined (Roboflow), obtained via the GLIP-curated
archive, CC BY 4.0. No Aquarium images or derived overlays were redistributed.
