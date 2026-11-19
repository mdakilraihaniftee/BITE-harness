# Legacy archive index

PARSEC-VL Phase 1 moved research material that the course project does not use
out of the active repository. Nothing was discarded: every file is in git history
(commit `9f571f6`) and in a verified copy at `../BITE-harness-legacy-archive/`
(original relative paths under `files/`, SHA-256 manifest, `inventory.json` with the
dependency check for each file, restore instructions in `ARCHIVE_INDEX.md`).

Restore one path: `git checkout 9f571f6 -- <path>`; restore all: `rsync -a ../BITE-harness-legacy-archive/files/ ./`.

| Archived path | Files | Purpose | Dependency check |
|---|---:|---|---|
| `docs/bite` | 114 | BITE research documents (phase reports, protocols, schemas, analyses) | only scripts/bite, evaluation_kit/bite_*, tests/bite_* and README research sections; no runtime import |
| `scripts/bite` | 65 | BITE experiment scripts (collection, calibration, pilots, readiness assessments) | standalone CLIs; referenced only by docs/bite and README research sections |
| `evaluation_kit/bite_calibration` | 71 | BITE calibration/collection research pipeline | imported only by scripts/bite and tests/bite_calibration; not by evaluation_kit core, runtime or Studio |
| `evaluation_kit/bite_collection` | 25 | BITE controlled evidence-collection executor | imported only by scripts/bite and tests/bite_collection |
| `tests/bite_calibration` | 12 | tests of the archived calibration pipeline | all 122 baseline failures/errors: need outputs/bite/* frozen artifacts absent from this machine |
| `tests/bite_collection` | 3 | tests of the archived collection pipeline | same as above |
| `visualization` | 13 | separate ARGUS demo application from another course (user upload) | not imported by openvlharness, evaluation_kit, scripts or tests; separate __main__ app |
| `docs/STUDIO_STORY_REPORT.md` | 1 | Studio development report (superseded by docs/INVESTIGATION_STUDIO.md) | README and INVESTIGATION_STUDIO links only (updated) |
| `docs/STUDIO_V3_VALIDATION.md` | 1 | Studio v3 validation report (superseded) | README and INVESTIGATION_STUDIO links only (updated) |
| `docs/images/studio_story` | 9 | screenshots used only by STUDIO_STORY_REPORT.md | STUDIO_STORY_REPORT.md only |
| `docs/images/studio_story_verified` | 27 | screenshots used only by STUDIO_STORY_REPORT.md | STUDIO_STORY_REPORT.md only |
| `scripts/run_studio_inferences.sh` | 1 | launcher superseded by scripts/run_custom_inference.sh (same runner, more options) | README/INVESTIGATION_STUDIO references updated to run_custom_inference.sh |
| `README.md` | 1 | original BITE research README (research questions, evidence, workflows) | replaced by the PARSEC-VL README; harness instructions moved to docs/HARNESS_GUIDE.md |

**Kept on purpose.** `openvlharness/bite/` (an opt-in, off-by-default evidence
observer wired into the agent loop and capability layer, with its provenance,
geometry, and serialization helpers) and its tests `tests/bite/`; the core of
`evaluation_kit` (dataset loaders, runner, scoring, CLI); `validation/` (release
checks). **Not touched:** `outputs/` (ignored; raw results, run records, and any
frozen artifacts stay where they are) and local datasets under `data/`.
