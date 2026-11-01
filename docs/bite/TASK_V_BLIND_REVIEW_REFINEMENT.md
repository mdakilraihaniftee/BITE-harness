# Task V blind-review refinement

Protocol: **`bite.task_v_blind_adjudication_protocol.v2`**. Status: implemented;
human review pending.

The Phase 4B-2B-4 case identities, source-group sample, queue, and authoritative
completion validator are reused. The refined server adds an append-only event
layer rather than replacing the review system.

## Enforced sequence

1. The server returns only image, query, proposed box, dimensions, case/source
   identities and candidate digest. It does not return score, COCO label, GT,
   IoU, focused output, or diagnostic explanation.
2. A human submits `blind_first_pass_submitted`. This file is created
   exclusively and cannot be overwritten.
3. Only a matching reviewer/case event chain may submit `gt_revealed`. The
   server validates that its timestamp follows the blind event and only then
   returns concealed evidence.
4. An optional `post_reveal_judgment` is a separate event. Any changed endpoint,
   evidence control, or reference box requires a reason.
5. Finalization passes through the existing
   `bite.task_v_visual_adjudication.v1` validator and creates a separate human
   completion file exclusively.

Every event includes reviewer and human type, case, source group, candidate ID,
source/annotation/candidate digests, protocol version, timestamp, ambiguity
controls, and review data. Separate reviewer IDs form independent chains.
Viewing or revealing an image never marks a review complete. Resume uses saved
events, so progress survives interruption and multiple sessions.

The canvas supports an optional reviewer-drawn pixel-xyxy box before or after
reveal, with source dimensions, object class/note, occlusion/truncation flags,
reviewer and timestamp. The box is a research annotation, not amended COCO GT.

Run:

```bash
.venv/bin/python scripts/bite/serve_task_v_blind_review.py
.venv/bin/python scripts/bite/validate_adjudication_progress.py
```

The blind `/api/cases` payload was live-checked for all 235 queued cases; all
concealed fields were absent. All 235 source hashes reproduced. Completed human
reviews remain zero.

