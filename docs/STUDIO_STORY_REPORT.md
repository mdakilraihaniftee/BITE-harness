# Investigation Story implementation and validation

Validated November 18, 2026. The checkout already contained uncommitted Studio
work. This change completes that implementation in place, preserves those edits,
and leaves the separate `visualization/` application untouched. No commit, push,
real model inference, or tool-service inference was performed.

## A. Source of timeline noise

The Technical Trace renders one card per normalized runtime event. A single
tool investigation can emit a decision, request, start, budget reservation,
completion, evidence record, and working-memory write. Model lifecycle records,
message deliveries, notebook updates, and run-state transitions add more cards.
The architecture previously followed raw activity, so bookkeeping could dominate
its caption and animations even when the story grouped tool calls.

The committed frontend already had an initial story implementation. Its main
cards still included unchanged coordinator reassessments and separate review
conclusions; message grouping used adjacent peer bursts. The final layer folds
recorded related events, provides stable source-based identities, and preserves
independent messages that lack a causal link. Counts below distinguish the
committed story baseline from the full raw trace; they do not pretend this
checkout started without a story view.

## B. Semantic steps and correlation

`openvlharness/studio/static/story.js` supplies the same deterministic
`buildStory(visibleEvents)` transformation for live SSE and replay. Each step
contains its run and agent, semantic kind, title, factual summary, status,
optional public intent and assessment, tool arguments, artifact references,
source-event IDs, and related steps. IDs are `step-<first source event ID>`;
main numbers follow creation order.

* Tool events correlate by owner-qualified invocation/activity identity or a
  same-owner parent/causal reference. Legacy call IDs are scoped to their agent;
  later decisions/requests can open a new invocation when a model reuses an ID.
  Missing IDs never suppress a failed tool call. Single-agent identities are
  supported as well as `worker_NN` and coordinator identities.
* Requests immediately create running cards. Completion, failure, linked evidence,
  and working-memory writes update that card. Ordinary writes add a memory note.
  Unrelated hypotheses remain separate steps; the next recorded action is labelled
  chronologically, without claiming it explains the earlier observation.
* Assignment IDs join plans, assignment messages, delivery records, and worker
  starts. A same-owner `report_event_id` joins public report messages and peer
  broadcasts to the recorded worker conclusion. Identical text alone never
  establishes a relationship. Replies require a recorded earlier message ID and
  reversed sender/recipient identities.
* Optional notebooks fold into the matching agent phase. An unchanged review
  conclusion updates its review card. Synthesis, finalization, final answer, and
  completion form one final step. Estimate changes remain individual main steps;
  ordinary retained estimates are optional routine steps.
* Tool failures, exhausted budgets, failed reviews, failed message delivery,
  failed model/memory operations, and terminal failures remain visible. Public
  rationale and result assessment say they were not recorded when absent.

Only the visible prefix is processed. No future result, reply, estimate, final
answer, or later interpretation enters an earlier replay position. The audited
real runs passed 721 total prefix checks for stable IDs and prefix-only sources.

## C. Actual run measurements

The following measurements use persisted records, not new inference. Raw files
were read without modification. The committed-story column was computed from
`git show HEAD:openvlharness/studio/static/story.js`; the final column uses the
current module. Routine cards and round dividers are excluded from main counts.

| Persisted run | Raw trace cards, before and after | Committed story main cards | Final story main cards | Tool calls preserved | Sent messages represented |
| --- | ---: | ---: | ---: | ---: | ---: |
| `real_fsc147_row0_studio` | 95 | 16 | 16 | 4 / 4 | 8 / 8 |
| `example_fsc147_row25` | 185 | 21 | 19 | 6 / 6 | 10 / 10 |
| `fsc147_val_row_25_20261118_164340` | 301 | 31 | 33 | 8 / 8 | 28 / 28 |
| `fsc147_val_row_10_20261116_210721` | 136 | 21 | 21 | 9 / 9 | 8 / 8 |

The four-worker run has more story cards than the earlier implementation because
uncorrelated messages are kept independently. A smaller fixed count is not a
correctness target.

For `example_fsc147_row25` specifically:

| Measurement | Recorded | Represented in final story |
| --- | ---: | ---: |
| Tool invocations | 6 | 6 |
| Sent messages | 10 | 10, including messages folded into report/assignment details |
| Worker hypothesis events | 4 | 4 |
| Explicit worker revisions | 1 | 1 |
| Coordinator estimate events | 2 | 2: provisional and confirming finalization |
| Important failed events | 0 | 0 |

Failures and an actual provisional revision are exercised by persisted scripted
fixtures, explicitly marked as fixtures:

| Fixture | Raw events | Main steps | Tool calls | Estimate events represented | Failed events represented |
| --- | ---: | ---: | ---: | ---: | ---: |
| `fixture_w1_memoff_peeroff` | 102 | 11 | 3 / 3 | 3 / 3, including 4 → 5 | 0 / 0 |
| `fixture_w2_memon_peeron` | 179 | 15 | 4 / 4 | 2 / 2 | 0 / 0 |
| `fixture_w4_memoff_peeron` | 380 | 35 | 16 / 16 | 2 / 2 | 7 / 7 |

Machine-readable details, including step titles and source IDs, are in
[semantic-audit.json](images/studio_story_verified/semantic-audit.json) and
[fixture-audit.json](images/studio_story_verified/fixture-audit.json).

One actual interleaved raw excerpt from `example_fsc147_row25` is:

```text
32 Worker 2 DECISION_SUMMARY_RECORDED
33 Worker 2 TOOL_CALL_REQUESTED
35 Worker 2 TOOL_CALL_STARTED
37 Worker 1 DECISION_SUMMARY_RECORDED
38 Worker 1 TOOL_CALL_REQUESTED
40 Worker 1 TOOL_CALL_STARTED
41 Worker 1 TOOL_CALL_COMPLETED
42 Worker 1 EVIDENCE_OBSERVED
```

The resulting story includes:

```text
03 Worker 2 used Visual Grounding
   Visual Grounding returned 46 regions, an image.
04 Worker 1 used Zoom In
   Zoom In returned a cropped image (tool_generated_image_1).
05 Worker 1 used Visual Grounding
   Visual Grounding returned 50 regions, an image.
...
17 Worker 1 revised its answer from 50 to 46
18 Coordinator formed a provisional estimate: 46
19 Coordinator finalized the answer: 46
```

These are recorded predictions and tool outputs, not correctness claims. The
separate authorized reference panel reports that this run's final count was
incorrect. The story never manufactures a corrected answer.

## D. UI and screenshots

Investigation Story is the default. Each main card has a number, agent, short
title, summary, and outcome; expanded details show input, result, recorded intent
and assessment, memory notes, and underlying-event navigation. Technical Trace
keeps the complete public event on expansion, including arrays longer than the
30-item preview limit and the exact timestamp. Hidden-reasoning keys remain
excluded.

The compact team, full graph, selected step, evidence panel, and original-image
ROI remain synchronized. Selecting a tool shows its exact agent/tool path;
clicking the tool opens the corresponding story card. Routine memory writes and
delivery bookkeeping do not pulse the graph in story mode. Technical activity is
available through the View menu, and explicitly selected trace events remain
inspectable.

| Capture | Source |
| --- | --- |
| [Main investigation story](images/studio_story_verified/story/story-01-main-story.png) | Persisted real FSC-147 run |
| [Expanded tool and ROI](images/studio_story_verified/story/story-02-expanded-tool-investigation.png) | Same real run |
| [Worker communication](images/studio_story_verified/story/story-03-worker-communication.png) | Persisted two-worker fixture |
| [Coordinator estimate revision](images/studio_story_verified/story/story-04-coordinator-estimate-revision.png) | Persisted one-worker fixture |
| [Important failures and budgets](images/studio_story_verified/story/story-05-failure-and-budget-stop.png) | Persisted four-worker fixture |
| [Technical Trace](images/studio_story_verified/story/story-06-technical-trace.png) | Same real run |
| [Light theme](images/studio_story_verified/story/story-07-light.png) | Same real run |
| [Dark theme](images/studio_story_verified/story/story-08-dark.png) | Same real run |

Additional screenshots in `images/studio_story_verified/matrix/` cover 1–4 workers,
memory/communication settings, sealed/released references, replay positions,
evidence synchronization, expanded harness details, and laptop layout.

## E. Validation

* Focused Studio, multi-agent, and agent suite: **132 passed, 60 subtests passed**.
  The final frontend rerun also passed all four pytest wrappers; these include
  **15 semantic grouping/causality tests**, frontend reducer/layout checks, and
  answer-state/team tests on freshly persisted fixtures.
* Browser suites use headless Chrome and actual persisted event records:
  **29/29 story checks and 88/88 configuration/live checks passed**. Reports:
  [story interactions](images/studio_story_verified/story/browser-story-report.json)
  and [live/configuration matrix](images/studio_story_verified/matrix/browser-matrix-report.json).
  Checks include the default tab, exact graph path, reverse tool selection, all raw
  events, full tool payloads, running/completed replay identity, light/dark views,
  ROI/crops, evaluator authorization, sealed live labels, and stable live SSE IDs.
* Full repository run: **995 passed, 451 subtests passed; 68 failed and 55 setup
  errors**. Those failures concern absent frozen `outputs/bite/` research artifacts
  in calibration/collection tests. The README already documents this external
  artifact dependency. The focused Studio suite has no failures.
* `ruff check openvlharness/studio openvlharness/multi_agent/actors.py` passes.
  The broader lint invocation reports 14 existing findings in the orchestrator,
  fixture implementation, and pre-existing test code; unrelated files were not
  rewritten to address them. `git diff --check`, shell syntax, and JS syntax pass.
* The new launcher was checked with default, one-row and two-row dry runs,
  invalid/oversized batches, and label-sealed inspect-only dataset preflights for
  FSC-147 rows 0 and 10. Neither preflight called a model or tool.

The restricted sandbox initially blocked loopback sockets. Server/browser tests
were rerun with local socket access; this was an environment limitation, not a
Studio regression. One early legacy assertion was updated to require an explicit
message/report link rather than treating equal text as causality.

## F. Files

Files completed or updated during this turn:

* `openvlharness/studio/static/story.js`
* `openvlharness/studio/static/app.js`
* `tests/studio/js/story_semantics.test.cjs`
* `scripts/studio_browser_matrix.mjs`
* `scripts/run_studio_inferences.sh` (new)
* `README.md`, `docs/INVESTIGATION_STUDIO.md`, this report (new)
* `docs/images/studio_story_verified/`: eight story PNGs and their browser report;
  fifteen matrix PNGs and their browser report; the two audit JSON files above.

The existing task-related working-tree changes also include
`openvlharness/multi_agent/actors.py`, `openvlharness/studio/reference.py`,
`openvlharness/studio/static/{architecture-graph.js,index.html,styles.css,team-view.js}`,
`scripts/{studio_browser_check.mjs,studio_ui_model_check.cjs}`,
`tests/studio/{test_frontend_js.py,js/answer_story_team.test.cjs}`, and earlier
screenshots under `docs/images/studio_story/`. These were preserved and exercised
by the checks. Existing unrelated `visualization/` and
`docs/images/studio_v3/example/` files were preserved.

## G. Reproduction

Open a stored run without inference:

```bash
source scripts/env.sh
python scripts/studio_ctl.py ensure --run example_fsc147_row25 --open
```

Expand a story card and select **View underlying events**, or switch to Technical
Trace and clear its filters. The replay bar changes the shared visible event
prefix. View → Technical activity enables internal graph traffic.

Run one or two real dataset tasks with live visualization, with model/tool
services already running and the dataset prepared:

```bash
bash scripts/run_studio_inferences.sh 0
bash scripts/run_studio_inferences.sh 0 10
```

Each task uses the existing live launcher and opens its own run link. The default
is two workers plus coordinator. `STUDIO_NUM_AGENTS=1` selects one worker plus
coordinator. For a command-only preview:

```bash
bash scripts/run_studio_inferences.sh --dry-run 0 10
```

## H. Limits

Most real tool calls do not record a public rationale or post-result
interpretation. The UI states that absence and keeps worker claims distinct from
tool measurements. Older messages without report metadata remain independent
cards. Ambiguous or missing tool correlations are kept separate rather than
assigned by timing. Very old logs with reused call IDs and no invocation or parent
links cannot always disambiguate late evidence. An uncorrelated budget denial can
be a separate failure card alongside the tool failure; no causal link is invented
to reduce the count. Timeline rendering retains the existing 1,000-card bound.
