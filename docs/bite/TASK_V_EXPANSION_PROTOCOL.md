# Task V expansion protocol v1

Protocol: `bite.task_v_expansion.v1`; frozen SHA-256
`6e090887606e23de1f3e69a89fe6c194ce93d22163e9dffd8d363e11125a6a1c`.

The target frame is the 277-group Aquarium `calibration_fit` partition. The 20
Phase 4B-2B-2 pilot groups are excluded, leaving 257 previously unused groups.
Thirty groups were selected uniformly without replacement by
`python.random.Random(418).sample`; each eligible group has inclusion probability
30/257. The full frame, exclusions, selected order, source manifest digest, and
representative-image rule are frozen in
`outputs/bite/phase04b2b3/protocol/task_v_expansion_protocol.json`.

Every selected representative receives all seven approved source-vocabulary
queries: fish, jellyfish, penguin, puffin, shark, starfish, and stingray. Thus
the schedule has 210 states and uses neither GT presence nor SAM output. It
targets uniformly scheduled Aquarium source-vocabulary queries, not naturally
chosen VLM queries.

Every state receives one root grounding action. Every usable candidate receives
Zoom followed by same-class focused grounding from an isolated clone. Five of
the 30 selected groups were independently allocated to repeat control by
`Random(419).sample`, giving group-level allocation probability 5/30; execution
still requires a runtime candidate. Both branches share the same frozen parent.

| Component | Maximum dispatches |
| --- | ---: |
| Root grounding | 210 |
| Zoom + focused grounding | 420 |
| Five-group repeat control | 35 |
| Total hard cap | **665** |

The continuation budget remains three public calls per branch. Empty initial
results are retained and create no candidate hypothesis. Original and expansion
cohort/design IDs remain distinct.

The source manifest is
`61df2e5f2a817b022f07358ec5b63438c8cfb56973009cf854c7b460c86aebd4`.
The backend is `sam3_segment` with the existing Zoom padding 50 and existing
service configuration. The configured checkpoint name is `facebook/sam3`, but
the worker health endpoint does not attest the exact loaded revision; no
cryptographic checkpoint-equivalence claim is made.

Source attribution: Aquarium Combined (Roboflow), GLIP-curated archive,
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Selection and
protocol metadata are modifications/derived research records; source images are
not redistributed.
