"""Build internal, bias-aware Task V human-review cases and interface."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .adjudication_sampling import statistical_quality_sample, targeted_failure_sample
from .adjudication_schema import (
    CASE_VERSION,
    PROTOCOL_VERSION,
    pending_review,
    validate_case,
)


def _identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _candidate_size(box, *, image_width, image_height):
    area = max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])
    relative = area / (image_width * image_height)
    return "small" if relative < .05 else "medium" if relative < .25 else "large"


def build_review_cases(*, diagnostics, focused_pairs, cohort_id, query_design_id, adapter):
    pair_map = {row["state_id"]: row for row in focused_pairs}
    entry_map = {entry.entry_id: entry for entry in adapter.entries()}
    cases = []
    for row in diagnostics:
        pair = pair_map[row["state_id"]]
        entry = entry_map[row["source_entry_id"]]
        gt = adapter.load_offline_ground_truth(entry)
        class_id = gt.class_map.get(row["query"].casefold())
        same = [ann["bbox_xyxy"] for ann in gt.annotations if ann["category_id"] == class_id]
        other = [
            {"bbox_xyxy": ann["bbox_xyxy"], "category_id": ann["category_id"]}
            for ann in gt.annotations if ann["category_id"] != class_id
        ]
        label50 = row["label_iou_0_50"]
        label75 = row["label_iou_0_75"]
        case_core = {
            "state_id": row["state_id"], "cohort_id": cohort_id,
            "source_group_id": row["source_group_id"], "query": row["query"],
        }
        focused = pair.get("focused_aligned_candidate")
        case = {
            "schema_version": CASE_VERSION,
            "case_id": "review_case:" + _identity(case_core),
            **case_core,
            "query_design_id": query_design_id,
            "partition": "calibration_fit",
            "source_entry_id": row["source_entry_id"],
            "source_image_path": gt.provenance["source_image_path"],
            "source_image_sha256": row["source_image_sha256"],
            "annotation_sha256": gt.provenance["annotation_sha256"],
            "annotation_version": "Aquarium train annotations_without_background.json frozen Phase 4B-2B-1A",
            "image_width": row["image_width"], "image_height": row["image_height"],
            "initial_candidate_id": row["candidate_id"],
            "initial_box_root_xyxy": row["bbox_root_xyxy"],
            "initial_score": row["raw_score"],
            "candidate_size": _candidate_size(
                label50["bbox_for_matching_xyxy"],
                image_width=row["image_width"], image_height=row["image_height"],
            ),
            "H_annotation": {
                "0.5": "positive" if label50["official_tp"] else "negative",
                "0.75": "positive" if label75["official_tp"] else "negative",
            },
            "H_visual_review": "not_reviewed",
            "diagnostic_primary": row["primary_diagnosis_iou_0_50"],
            "best_eligible_iou": label50["max_eligible_iou"],
            "same_class_gt_boxes_xyxy": same,
            "nearby_other_class_gt_boxes": other,
            "focused_association_category": pair["focused_association_category"],
            "focused_box_root_xyxy": focused["bbox_root_xyxy"] if focused else None,
            "focused_score": focused["raw_scores"][0] if focused else None,
            "zoom_crop_root_xyxy": pair["zoom_crop"]["crop_rectangle_parent_xyxy"],
            "zoom_crop_dimensions": [pair["zoom_crop"]["child_width"], pair["zoom_crop"]["child_height"]],
            "blind_stage_fields": [
                "source_image", "query", "initial_box_root_xyxy", "initial_score", "candidate_size",
            ],
            "reveal_stage_fields": [
                "H_annotation", "same_class_gt_boxes_xyxy", "nearby_other_class_gt_boxes",
                "best_eligible_iou", "zoom_crop_root_xyxy", "focused_box_root_xyxy",
            ],
            "review_protocol_version": PROTOCOL_VERSION,
            "source_attribution": "Aquarium Combined (Roboflow), CC BY 4.0; GLIP-curated archive",
        }
        cases.append(validate_case(case))
    return cases


def write_review_bundle(output_dir, cases, *, seed=420):
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    statistical = statistical_quality_sample(cases, seed=seed)
    targeted = targeted_failure_sample(cases)
    union_ids = sorted(set(statistical["case_ids"]) | set(targeted["case_ids"]))
    case_map = {case["case_id"]: case for case in cases}
    queue = [case_map[case_id] for case_id in union_ids]
    with (output / "review_cases.jsonl").open("w") as stream:
        for case in cases:
            stream.write(json.dumps(case, sort_keys=True) + "\n")
    with (output / "pending_adjudications.jsonl").open("w") as stream:
        for case in queue:
            stream.write(json.dumps(pending_review(case["case_id"], case["annotation_sha256"]), sort_keys=True) + "\n")
    for name, value in (
        ("statistical_review_sample.json", statistical),
        ("targeted_review_sample.json", targeted),
        ("review_queue.json", {
            "schema_version": "bite.task_v_review_queue.v1", "case_ids": union_ids,
            "case_count": len(union_ids), "human_reviews_completed": 0,
            "human_review_status": "PENDING", "ai_judgments_present": False,
        }),
    ):
        (output / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    (output / "index.html").write_text(_html())
    return {"statistical": statistical, "targeted": targeted, "queue_count": len(queue)}


def _html():
    return """<!doctype html>
<html><head><meta charset="utf-8"><title>BITE Task V adjudication</title>
<style>body{font:15px system-ui;margin:2rem;max-width:1200px}.grid{display:grid;grid-template-columns:2fr 1fr;gap:1rem}canvas{max-width:100%;border:1px solid #777}fieldset{margin:.7rem 0}.hidden{display:none}label{display:block;margin:.35rem 0}button{margin:.5rem}.warn{color:#8a3b00}</style></head>
<body><h1>Task V visual adjudication</h1><p class="warn">Internal CC BY 4.0 research review. Images must not be redistributed. Automated labels are hidden until reveal.</p>
<p><button id="prev">Previous</button><button id="next">Next</button><span id="position"></span></p>
<div class="grid"><div><canvas id="canvas"></canvas></div><div><h2 id="query"></h2><div id="blind"></div><button id="reveal">Reveal GT and machine label</button><div id="revealed" class="hidden"></div></div></div>
<form id="review"><fieldset><legend>Human controls</legend><div id="controls"></div></fieldset>
<label>Visual judgment <select name="H_visual_review" required><option value="">Select</option><option>visually_supported_positive</option><option>visually_supported_negative</option><option>possible_annotation_omission</option><option>class_identity_ambiguous</option><option>localization_ambiguous</option><option>insufficient_image_evidence</option></select></label>
<label>Applicable IoU thresholds <select name="applicable_iou_thresholds" multiple required><option selected>0.5</option><option selected>0.75</option></select></label>
<label>Corrected-label defensibility <select name="corrected_label_status" required><option value="">Select</option><option>no_correction_proposed</option><option>visual_only_not_benchmark_correction</option><option>correction_potentially_defensible_requires_annotation_amendment</option><option>indeterminate</option></select></label>
<label>Defensibility reason <textarea name="corrected_label_reason" required></textarea></label>
<label>Reviewer ID <input name="reviewer_id" required></label><label>Comments <textarea name="comments"></textarea></label><button type="submit">Save human review</button></form><pre id="status"></pre>
<script>
const names=['object_present_in_proposed_region','class_appears_correct','box_reasonably_localizes_object','relevant_annotation_appears_missing','nearby_competing_instance','image_evidence_inconclusive'];
controls.innerHTML=names.map(n=>`<label>${n} <select name="${n}" required><option value="">Select</option><option>yes</option><option>no</option><option>uncertain</option></select></label>`).join('');
let cases=[],i=0,revealedFlag=false,img=new Image(); const ctx=canvas.getContext('2d');
function box(b,color,w=3){if(!b)return;ctx.strokeStyle=color;ctx.lineWidth=w;ctx.strokeRect(b[0],b[1],b[2]-b[0],b[3]-b[1]);}
function draw(){let c=cases[i]; canvas.width=c.image_width;canvas.height=c.image_height;ctx.drawImage(img,0,0);box(c.initial_box_root_xyxy,'red',5);if(revealedFlag){c.same_class_gt_boxes_xyxy.forEach(b=>box(b,'lime',3));c.nearby_other_class_gt_boxes.forEach(x=>box(x.bbox_xyxy,'cyan',2));box(c.zoom_crop_root_xyxy,'orange',3);box(c.focused_box_root_xyxy,'magenta',4);}}
function show(){let c=cases[i];revealedFlag=false;document.getElementById('revealed').className='hidden';position.textContent=` ${i+1}/${cases.length} ${c.case_id}`;query.textContent=`Query: ${c.query}`;blind.textContent=`source_group=${c.source_group_id} score=${c.initial_score} size=${c.candidate_size}`;img.onload=draw;img.src='/source/'+encodeURIComponent(c.case_id);}
reveal.onclick=()=>{revealedFlag=true;let c=cases[i];document.getElementById('revealed').className='';document.getElementById('revealed').textContent=`H_annotation=${JSON.stringify(c.H_annotation)} best IoU=${c.best_eligible_iou} focus=${c.focused_association_category}`;draw()};
prev.onclick=()=>{i=(i+cases.length-1)%cases.length;show()};next.onclick=()=>{i=(i+1)%cases.length;show()};
review.onsubmit=async e=>{e.preventDefault();let c=cases[i],fd=new FormData(review),controls={};names.forEach(n=>controls[n]=fd.get(n));let body={schema_version:'bite.task_v_visual_adjudication.v1',case_id:c.case_id,reviewer_id:fd.get('reviewer_id'),reviewer_type:'human',reviewed_at:new Date().toISOString(),protocol_version:'bite.task_v_adjudication_protocol.v1',annotation_sha256:c.annotation_sha256,H_visual_review:fd.get('H_visual_review'),controls,applicable_iou_thresholds:fd.getAll('applicable_iou_thresholds'),corrected_label_status:fd.get('corrected_label_status'),corrected_label_reason:fd.get('corrected_label_reason'),comments:fd.get('comments')||''};let r=await fetch('/api/reviews',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});status.textContent=await r.text()};
fetch('/api/cases').then(r=>r.json()).then(x=>{cases=x;show()});
</script></body></html>"""
