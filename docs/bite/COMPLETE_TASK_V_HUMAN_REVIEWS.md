# Complete Task V human reviews

Human review status is **pending**: Set A is 0/120, Set B is 0/228, and the
235-case union is 0/235. Visual reliability and omission prevalence are unknown.

Use a local loopback address only. Aquarium images are internal CC BY 4.0
research material and must not be exposed through a public tunnel.

1. Launch Set A, the immediate statistical priority:

   ```bash
   source scripts/env.sh
   .venv/bin/python scripts/bite/serve_task_v_blind_review.py \
     --sample set-a --host 127.0.0.1 --port 8115 \
     --output outputs/bite/phase04c1b
   ```

2. Open `http://127.0.0.1:8115` locally. The server, not a display toggle,
   withholds detector score, annotation label, GT, IoU, focused output and
   diagnostics.
3. Enter a stable human reviewer ID. Judge object presence, class correctness,
   and localization before reveal. Optional pixel reference boxes are allowed.
4. Submit the immutable blind first pass. This creates
   `blind_first_pass_submitted`; it cannot be overwritten.
5. Reveal GT only after submission. The server records a later `gt_revealed`
   event.
6. If interpretation changes, submit a separate post-reveal record and reason.
   The blind record remains unchanged.
7. Finalize through the authoritative existing human-completion validator.
   Merely viewing an image never completes it.
8. To resume, enter the same reviewer ID and use the resume button. Event files
   persist across server sessions.
9. Validate identities and progress:

   ```bash
   .venv/bin/python scripts/bite/check_task_v_review_progress.py
   .venv/bin/python scripts/bite/validate_adjudication_progress.py \
     --output outputs/bite/phase04c1b
   ```

10. Read `outputs/bite/phase04c1b/review_progress/progress.json` for Set A,
    Set B, unresolved, post-reveal, second-review and omission-investigation
    counts.

The second-review sample is frozen in `second_review_sample.json`: five Set A
source groups (two pilot, three expansion), containing 25 cases, selected by
the lowest SHA-256 of `seed:cohort:source_group_id`. The second reviewer must use
a distinct reviewer ID and must not see the first reviewer's judgment. The API
does not return other reviewers' judgments before submission. Agreement is not
reported until genuine comparable double reviews exist.

Set B is targeted and must never be used as an unbiased omission-prevalence
sample. Set A inclusion probabilities remain 10/19 for pilot groups and 15/30
for expansion groups.

