# Phase 4C-1F: controlled semantic verification pilot (preflight only)

Report date: **2026-11-02**. Status: **OFFLINE_PREFLIGHT_PASS /
AUTHORIZATION_ABSENT / PILOT_NOT_EXECUTED**.

The phase specification is explicitly not an authorization, and no
researcher-written authorization exists. The phase therefore stopped after
offline preflight, as specified.

- **Real VLM calls: 0.**
- SAM 3 calls: 0.
- No service was started.
- No labels were opened for the pilot, and no pilot-subset label statistics
  were computed.
- No validation or internal-test access, and no changes to the agent or
  evaluator.
- No commit.

## What was done

1. **Frozen pilot verified** (`TASK_V_SEMANTIC_PILOT_EXECUTION_REPORT.md` §2):
   - 15 groups, 105 states and 4 no-candidate states;
   - all 101 cases re-derived from stored states and all 101 rendered-input
     digests reproduced;
   - original raw-before-GT chains valid;
   - scores and queries consistent with the 4C-1D runtime table, and never in
     the prompt;
   - full prompt, ontology, design and manifest digests match, and the 4C-1E
     artifacts are unchanged.
2. **Identifier safety.** The 101 cases share only 12 local `candidate_id`
   values. A scoped identity `(source_run_id, state_id, candidate_id,
   action_version)` is now recorded per observation; all 101 are unique. Labels
   join on `state_id` with a candidate check.
3. **Backend readiness.**
   - The endpoint is loopback `127.0.0.1:8222` (vLLM 0.18.1 launch script).
   - The service is not running, and the 4 L40S GPUs are idle.
   - The Qwen3-VL-8B cache is at the pinned revision, and all 4 weight shards
     matched their SHA-256 blob names (`CACHE_CONTENT_VERIFIED_ONLY`).
   - Load-time identity is unverifiable through the endpoint; the served model
     name is checked per response.
   - Decoding is greedy.
   - The request estimate was redone with the processor's real limits: about
     102k visual and 51k text tokens, with the largest request ≈ 2.3k tokens.
4. **Runner hardened** (`semantic_pilot_protocol.py`). The live binding now also
   requires the ontology digest, the model id, the exact endpoint (loopback
   unless separately approved), the run directory, a cap no larger than 101 and
   an optional execution window. In addition:
   - The cap is **cumulative** across canary, main run and resumes. Before this
     phase it was counted per invocation, which would have let a canary plus a
     resume exceed the cap.
   - A canary of at most 5 cases counts toward the cap.
   - The run halts after 3 consecutive failures, and when the served model
     differs from the authorized one. Any partial case blocks all further
     dispatch.
   - Each record carries the authorization digest, timestamps and the scoped
     identity.
5. **Post-collection analysis written before data** (`semantic_pilot_analysis.py`,
   `analyze_semantic_pilot.py`). It does the following, in order:
   - validates every observation against the frozen lineage;
   - finalizes the GT-free table digest before opening labels, with a
     hash-chained event log;
   - joins the canonical 4C-1D labels by state;
   - runs the frozen leave-one-group-out models;
   - computes paired bootstrap contrasts (seed 467) for Brier, log loss and
     error, plus the MS − MZ contrast added before data;
   - produces decision and cost screens and stratified failure analysis;
   - applies the frozen decision rule, plus a conservative guard overlay fixed
     before data.

   It has been tested on synthetic data only. Without a complete live run it
   refuses to start.
6. **Measured Zoom costs extracted** from archived GT-free branch records: a
   median of 218 ms for the two dispatches over 203 branches
   (`BITE_ACTION_COST_COMPARISON.md`).
7. **Theory corrections** (dated notes; no measurement changed):
   - The fitted-model probability displacement (about 0.01 RMS, about 1e-4
     Brier) is **not an information ceiling**. The identity holds only for the
     true conditional probabilities.
   - The Hoeffding sample sizes (about 240k groups for ±0.005) are
     **worst-case, distribution-free**. At the observed variance, empirical
     Bernstein needs about 4,400, and a normal approximation, which has no
     finite-sample guarantee, needs about 74. The requirement depends on the
     range, variance, confidence level, precision, group dependence and target
     effect size.
   - **Exact offline replay requires coverage.** Only policies whose actions,
     observations and transitions are all in the recorded branches can be
     replayed. Adaptive policies cannot.

   The corrected documents are `BITE_DEPENDENT_EVIDENCE_VALUE_THEORY.md`,
   `BITE_ACTION_UTILITY_SCREENING.md`, `PHASE_04C1E_REPORT.md` and
   `TASK_V_AGENT_TASK_EXTENSION_PROPOSAL.md`. The 4C-1E implementation manifest
   is left as the historical record of their earlier text.

## Not done (by design)

- No canary.
- No collection.
- No predictive or decision results.
- No research decision about semantic usefulness.

The result documents state this explicitly and contain no tables.

## Privacy observation

An unrelated `cloudflared` quick tunnel (another project) exposes a local image
host at `127.0.0.1:8112`. The pilot never uses it, and it was not touched. The
researcher should confirm it is intended.

## Next step

Live execution needs two actions from the researcher:

1. Start `bash scripts/service.sh qwen`.
2. Write the authorization JSON described in
   `outputs/bite/phase04c1f/authorization/authorization_requirements.json`.

Then: canary (`--canary 5`), inspect it without labels, `--resume`, and run
`analyze_semantic_pilot.py`.

Artifacts: `outputs/bite/phase04c1f/` (`preflight/`, `authorization/`,
`research_decision/`, `tests/`, plus the manifests).
