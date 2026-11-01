# Task V expansion results

**Status: SUCCESS.** The real two-group canary passed before continuation, and
the same frozen run resumed into all 30 groups.

| Quantity | Result |
| --- | ---: |
| Source groups / images | 30 / 30 |
| Scheduled / completed states | 210 / 210 |
| Candidate-present / no-candidate | 203 / 7 |
| Root / Zoom / focused / repeat calls | 210 / 203 / 203 / 35 |
| Failed dispatches / partial compositions | 0 / 0 |
| Actual logical dispatches | **651** |
| Hard cap | 665 |

All 203 usable candidates received the prescribed Zoom→focused path. All 35
eligible repeat-control states executed; all repeated boxes, scores, and masks
were exactly equal at full precision.

## Initial-candidate offline labels

| IoU | Positive | Negative | Unknown |
| --- | ---: | ---: | ---: |
| 0.50 | 31 | 172 | 0 |
| 0.75 | 23 | 180 | 0 |

At IoU 0.50, per-class positive/negative counts are: fish 9/20,
jellyfish 0/29, penguin 3/27, puffin 4/24, shark 9/20, starfish 2/27,
and stingray 4/25. Per-size counts are small 19/103, medium 12/66, and
large 0/3. Twenty-seven invalid candidates had retained SAM3 score at least
0.90 (this threshold is a descriptive audit definition, not a calibrated
probability).

Negative primary explanations are 159 `no_annotated_instance`, 5
`insufficient_localization`, 7 `wrong_instance_or_class_confusion`, and 1
`wrong_location`. All 203 labels reproduced exactly under independent geometry;
172 negatives remain in the visual-review queue.

Median/p95 latency in milliseconds was root 513.4/850.1, Zoom 75.2/156.7,
focused grounding 147.4/262.4, and repeat 513.8/578.6. The measured audit saw
3,405 files and roughly 669.6 MB, including 853 content artifacts and 327.2 MB
of content-addressed artifacts. Multiple class states from one image and all
same-image branches are dependent.

The worker reported healthy SAM3 service compatibility but did not attest exact
checkpoint weights. No Qwen call, training, probability fit, posterior, planner,
or certificate was performed.

Source attribution: Aquarium Combined (Roboflow), GLIP-curated archive,
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Source-derived
overlays/artifacts remain internal.
