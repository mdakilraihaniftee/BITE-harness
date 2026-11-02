"""Post-collection analysis of the semantic-verification pilot (written before data).

Order of operations is enforced: validate raw observations against the frozen
manifest, finalize the GT-free feature table and its digest, and only then join
the canonical Phase 4C-1D annotation-proxy labels and archived Zoom features by
``state_id`` with a candidate-identity check. Models, folds and the primary
estimand are the frozen Phase 4C-1E design; nothing here adds a model variant.
"""

from __future__ import annotations

import hashlib
import random
import statistics
from collections import Counter, defaultdict

import numpy as np

from .action_utility_screen import screen_action
from .calibration_metrics import (
    calibration_metrics,
    group_balanced_metrics,
    reliability_summary,
)
from .paired_zoom_evaluation import paired_difference
from .semantic_comparison_design import (
    BASELINE,
    BOOTSTRAP_SEED,
    MODEL_SPECS,
    classify_pilot,
    evaluate_comparisons,
    logo_crossfit,
)
from .semantic_feature_extractor import join_offline_labels
from .semantic_observation_schema import FIELD_VALUES

ANALYSIS_VERSION = "bite.semantic_pilot_analysis.v1"
ENDPOINTS = ("0.5", "0.75")
METRICS = ("brier_score", "log_loss", "decision_error")
# Contrasts of already-specified models. MS vs MZ was added in Phase 4C-1F before
# any semantic observation existed; it is not a new model.
REPORTED_CONTRASTS = (
    ("ms_semantic", BASELINE, "primary"),
    ("mz_zoom", BASELINE, "secondary"),
    ("mzs_zoom_semantic", "ms_semantic", "secondary_complementarity"),
    ("ms_semantic", "mz_zoom", "secondary_complementarity_added_4c1f_pre_data"),
    ("mzs_zoom_semantic", "mz_zoom", "secondary_complementarity"),
    ("ms_semantic_localization_secondary", "ms_semantic", "secondary_localization"),
)
LOGICAL_COST = {"mz_zoom": 2, "ms_semantic": 1, "mzs_zoom_semantic": 3}
ZOOM_FIELDS = ("initial_score", "score_difference", "score_change_observed",
               "association_ambiguous", "association_no_alignment")
MINIMUM_GROUPS_WITH_POSITIVES = 3


def validate_observations(observations, manifest, *, require_live=True):
    cases = {case["case_id"]: case for case in manifest["cases"]}
    seen = set()
    for row in observations:
        case = cases.get(row["case_id"])
        if case is None:
            raise ValueError(f"Observation for a case outside the frozen manifest: {row['case_id']}")
        if row["case_id"] in seen:
            raise ValueError(f"Duplicate observation for case {row['case_id']}")
        seen.add(row["case_id"])
        lineage = row["lineage"]
        if (row["state_id"] != case["state_id"]
                or lineage["original_candidate_id"] != case["original_candidate_id"]
                or lineage["source_image_sha256"] != case["source_image_sha256"]
                or lineage["region_render"]["render_sha256"] != case["region_render_sha256"]):
            raise ValueError(f"Observation lineage differs from the frozen case {row['case_id']}")
        if require_live and (row.get("mock") or row.get("execution_context", {}).get("mode") != "live"):
            raise ValueError("Primary analysis accepts live observations only")
    statuses = Counter(row["response_status"] for row in observations)
    latencies = [row["execution"]["latency_ms"] for row in observations]
    usage = Counter()
    for row in observations:
        for key, value in (row["execution"].get("token_usage") or {}).items():
            if isinstance(value, int):
                usage[key] += value
    return {
        "attempted": len(observations),
        "frozen_cases": len(cases),
        "missing_case_ids": sorted(set(cases) - seen),
        "complete": seen == set(cases),
        "response_status_counts": dict(sorted(statuses.items())),
        "valid_rate": statuses.get("valid", 0) / len(cases),
        "served_models": dict(Counter(row["backend"]["served_model_reported"] for row in observations)),
        "authorization_sha256": sorted({str(row.get("execution_context", {}).get("authorization_sha256"))
                                        for row in observations}),
        "token_usage_total": dict(usage),
        "latency_ms": {
            "count": len(latencies),
            "median": statistics.median(latencies) if latencies else None,
            "maximum": max(latencies) if latencies else None,
            "total": sum(latencies),
        },
    }


def canonical_targets(prediction_rows):
    """Per-state labels from the checksum-verified Phase 4C-1D OOF M0 rows."""
    targets = {}
    for row in prediction_rows:
        if row["model_name"] != "initial_score_only_m0":
            continue
        if row["state_id"] in targets:
            raise ValueError("Duplicate target row for a state")
        targets[row["state_id"]] = {
            "state_id": row["state_id"], "candidate_id": row["candidate_id"], "label": int(row["label"]),
            "endpoint": row["endpoint"], "annotation_scope_audit": row["annotation_scope_audit"],
        }
    return targets


def join_rows(table, finalized_rows_sha256, targets, zoom_rows):
    """Labels join only to the unchanged finalized table; Zoom features by state."""
    zoom = {row["state_id"]: row for row in zoom_rows}
    states = [row["state_id"] for row in table["rows"]]
    joined = join_offline_labels(table, [targets[state] for state in states],
                                 finalized_rows_sha256=finalized_rows_sha256)
    output = []
    for row in joined:
        archived = zoom[row["state_id"]]
        if archived["original_candidate_id"] != row["original_candidate_id"]:
            raise ValueError("Archived Zoom row refers to a different candidate hypothesis")
        output.append({
            **row, **{field: archived[field] for field in ZOOM_FIELDS},
            "annotation_scope_audit": targets[row["state_id"]]["annotation_scope_audit"],
        })
    return output


def support(rows):
    groups = defaultdict(lambda: [0, 0])
    for row in rows:
        groups[row["source_group_id"]][row["label"]] += 1
    positives = sum(row["label"] for row in rows)
    negatives = len(rows) - positives
    groups_with_positives = sum(1 for counts in groups.values() if counts[1])
    # LOGO training split lacks a class iff one held-out group holds all of that class.
    estimable = positives > 0 and negatives > 0 and all(
        counts[1] < positives and counts[0] < negatives for counts in groups.values())
    return {
        "candidate_count": len(rows),
        "source_group_count": len(groups),
        "positive_count": positives,
        "negative_count": negatives,
        "groups_with_positives": groups_with_positives,
        "logo_estimable": estimable,
    }


def paired_bootstrap(aligned, contrasts, *, replicates=2000, seed=BOOTSTRAP_SEED):
    grouped = defaultdict(list)
    for row in aligned:
        grouped[row["source_group_id"]].append(row)
    groups = sorted(grouped)
    rng = random.Random(seed)
    samples = {(m, b, metric, scope): [] for m, b, _ in contrasts for metric in METRICS
               for scope in ("case_level", "group_balanced")}
    first_hashes = []
    for replicate in range(replicates):
        selected = [rng.choice(groups) for _ in groups]
        if replicate < 10:
            first_hashes.append(hashlib.sha256("\n".join(selected).encode()).hexdigest())
        drawn = [{**row, "source_group_id": f"{i}:{g}"} for i, g in enumerate(selected) for row in grouped[g]]
        for (m, b, metric, scope), values in samples.items():
            values.append(paired_difference(drawn, m, b, metric, group_balanced=scope == "group_balanced"))
    output = {}
    for m, b, role in contrasts:
        entry = {"model": m, "baseline": b, "role": role}
        for scope in ("case_level", "group_balanced"):
            entry[scope] = {metric: {
                "observed_difference": paired_difference(aligned, m, b, metric, group_balanced=scope == "group_balanced"),
                "lower_2_5": float(np.quantile(samples[(m, b, metric, scope)], .025)),
                "upper_97_5": float(np.quantile(samples[(m, b, metric, scope)], .975)),
            } for metric in METRICS}
        output[f"{m}_minus_{b}"] = entry
    return {
        "method": "paired percentile source-group bootstrap over fixed LOGO predictions",
        "seed": seed, "replicates": replicates, "invalid_replicates": 0,
        "candidate_rows_resampled_iid": False, "refit_inside_bootstrap": False,
        "first_ten_draw_sha256": first_hashes,
        "sign_convention": "model loss minus baseline loss; negative favors model",
        "contrasts": output,
    }


def model_metrics(aligned):
    output = {}
    for model in MODEL_SPECS:
        simple = [{"source_group_id": r["source_group_id"], "label": r["label"],
                   "probability": r["probabilities"][model]} for r in aligned]
        labels = [r["label"] for r in simple]
        probabilities = [r["probability"] for r in simple]
        output[model] = {
            "case_level": calibration_metrics(labels, probabilities),
            "group_balanced": group_balanced_metrics(simple, "probability"),
            "reliability": reliability_summary(labels, probabilities),
        }
    return output


def evaluate_endpoint(rows, *, replicates=2000, seed=BOOTSTRAP_SEED):
    counts = support(rows)
    if not counts["logo_estimable"]:
        return {"status": "NON_ESTIMABLE", "support": counts,
                "reason": "a leave-one-group-out training split lacks a class; folds are not altered"}
    aligned = logo_crossfit(rows)
    frozen = evaluate_comparisons(aligned, replicates=replicates, seed=seed)
    decisions = {
        model: screen_action(aligned, baseline=BASELINE, treatment=model, action_cost=cost,
                             endpoint=rows[0]["endpoint"], replicates=replicates, seed=seed)
        for model, cost in LOGICAL_COST.items()
    }
    return {
        "status": "ESTIMATED",
        "support": counts,
        "predictions": aligned,
        "model_metrics": model_metrics(aligned),
        "frozen_design_comparisons": frozen,
        "paired_uncertainty": paired_bootstrap(aligned, REPORTED_CONTRASTS, replicates=replicates, seed=seed),
        "decision_screens": decisions,
        "primary_brier_difference": frozen[f"ms_semantic_minus_{BASELINE}"]["brier_difference"],
    }


def _stratum(row):
    if row["label"]:
        return "annotation_positive"
    if row["annotation_scope_audit"] == "no_annotated_queried_class_instance":
        return "negative_no_queried_class_annotation"
    return "negative_queried_class_annotated_or_other"


def failure_analysis(rows):
    """Descriptive cross-tabulations after label join; no predictor is derived here."""
    fields = ["semantic_response_status", "semantic_compatibility"] + [
        f"semantic_{name}" for name in FIELD_VALUES if name != "region_content"]
    by_stratum = defaultdict(lambda: defaultdict(Counter))
    by_query = defaultdict(lambda: defaultdict(Counter))
    for row in rows:
        for field in fields:
            by_stratum[_stratum(row)][field][str(row[field])] += 1
            by_query[row["query"]][field][str(row[field])] += 1
    matched = [row for row in rows if row["semantic_compatibility"] == "match"]
    return {
        "endpoint": rows[0]["endpoint"],
        "stratum_counts": dict(Counter(_stratum(row) for row in rows)),
        "by_stratum": {s: {f: dict(c) for f, c in v.items()} for s, v in sorted(by_stratum.items())},
        "by_query": {q: {f: dict(c) for f, c in v.items()} for q, v in sorted(by_query.items())},
        "semantic_match_by_localization_and_label": dict(Counter(
            f"localization={row['semantic_region_localization']}|label={row['label']}" for row in matched)),
        "annotation_absence_treated_as_visual_absence": False,
        "semantic_match_treated_as_localization_verification": False,
    }


def research_decision(valid_rate, endpoint_results):
    """Frozen 4C-1E rule plus a stricter guard overlay fixed in 4C-1F before data:
    PROCEED is downgraded to INCONCLUSIVE unless every endpoint has positives in at
    least three groups and no single held-out group reverses the primary sign."""
    primary = {ep: result.get("primary_brier_difference") for ep, result in endpoint_results.items()}
    frozen = classify_pilot(valid_rate, primary)
    guards = []
    for endpoint, result in sorted(endpoint_results.items()):
        if result["status"] != "ESTIMATED":
            guards.append(f"IoU {endpoint}: {result['status']}")
            continue
        if result["support"]["groups_with_positives"] < MINIMUM_GROUPS_WITH_POSITIVES:
            guards.append(f"IoU {endpoint}: positives in fewer than {MINIMUM_GROUPS_WITH_POSITIVES} groups")
        loo = result["decision_screens"]["ms_semantic"]["influence_sensitivity"]["leave_one_group_out"]
        if loo["brier_utility_gross"]["minimum"] <= 0:
            guards.append(f"IoU {endpoint}: removing one group erases the semantic Brier gain")
    final = "INCONCLUSIVE" if frozen == "PROCEED_TO_LARGER_FIT_COLLECTION" and guards else frozen
    return {
        "frozen_rule_outcome": frozen,
        "guard_overlay_failures": guards,
        "decision": final,
        "primary_brier_difference_by_endpoint": primary,
        "valid_rate": valid_rate,
        "larger_collection_authorized": False,
        "universal_claim_about_vlm_verification": False,
    }
