#!/usr/bin/env python3
"""Serve the server-enforced blind-first refinement of the existing Task V review system."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from evaluation_kit.bite_calibration.adjudication_schema import (
    PROTOCOL_VERSION,
    REVIEW_VERSION,
)
from evaluation_kit.bite_calibration.blind_review import (
    BLIND_EVENT_VERSION,
    BLIND_PROTOCOL_VERSION_V3,
    append_event,
    candidate_digest,
    load_event_chain,
    progress_summary,
    validate_final_completion,
)

ROOT = Path(__file__).resolve().parents[2]
ACTIVE_BLIND_PROTOCOL_VERSION = BLIND_PROTOCOL_VERSION_V3


def _now():
    return datetime.now(UTC).isoformat()


def _visual_label(endpoint, controls):
    if controls["image_evidence_inconclusive"] == "yes":
        return "insufficient_image_evidence"
    if endpoint.get("schema_version") == "bite.visual_verification.v2":
        if endpoint["binary_visual_endpoint"] == 1:
            return "visually_supported_positive"
        if endpoint["binary_visual_endpoint"] == 0:
            return "visually_supported_negative"
        if endpoint["class_correctness"] == "ambiguous":
            return "class_identity_ambiguous"
        if endpoint["localization_adequacy"] == "ambiguous":
            return "localization_ambiguous"
        return "insufficient_image_evidence"
    if endpoint["visual_plausibility"] == "ambiguous" or controls["class_appears_correct"] == "uncertain":
        return "class_identity_ambiguous"
    if endpoint["visual_localization"] == "ambiguous" or controls[
        "box_reasonably_localizes_object"
    ] == "uncertain":
        return "localization_ambiguous"
    if controls["relevant_annotation_appears_missing"] == "yes":
        return "possible_annotation_omission"
    if endpoint["binary_visual_endpoint"] == 1:
        return "visually_supported_positive"
    if endpoint["binary_visual_endpoint"] == 0:
        return "visually_supported_negative"
    return "insufficient_image_evidence"


def _html():
    return r"""<!doctype html><html><head><meta charset="utf-8"><title>BITE blind review v2</title>
<style>body{font:15px system-ui;margin:2rem;max-width:1200px}.grid{display:grid;grid-template-columns:2fr 1fr;gap:1rem}canvas{max-width:100%;border:1px solid #777}.hidden{display:none}label{display:block;margin:.35rem 0}fieldset{margin:.7rem 0}.warn{color:#8a3b00}</style></head><body>
<h1>Task V blind-first visual adjudication</h1><p class="warn">Internal CC BY 4.0 research review. Score, GT and focused evidence are server-concealed until the blind judgment is irreversibly submitted.</p>
<p id="progress"></p><button id="prev">Previous</button><button id="next">Next</button><span id="position"></span>
<div class="grid"><canvas id="canvas"></canvas><section><h2 id="query"></h2><p id="blindMeta"></p>
<form id="blindForm"><label>Reviewer ID <input name="reviewer_id" required></label><button type="button" id="resumeButton">Resume this reviewer's saved stage</button><label>Visual plausibility <select name="visual_plausibility" required><option></option><option>supported</option><option>unsupported</option><option>ambiguous</option><option>insufficient_evidence</option></select></label><label>Visual localization <select name="visual_localization" required><option></option><option>adequate</option><option>inadequate</option><option>ambiguous</option><option>insufficient_evidence</option></select></label><div id="blindControls"></div><label><input type="checkbox" id="drawBox"> Draw optional reference box by dragging on image</label><label>Object identity note <input name="object_identity_note"></label><label><input type="checkbox" name="occluded"> Occluded</label><label><input type="checkbox" name="truncated"> Truncated</label><button>Submit immutable blind first pass</button></form>
<button id="revealButton" disabled>Reveal score, GT and focused evidence</button><div id="revealed" class="hidden"></div>
<form id="postForm" class="hidden"><h3>Optional post-reveal adjustment</h3><label>Visual plausibility <select name="visual_plausibility" required><option>supported</option><option>unsupported</option><option>ambiguous</option><option>insufficient_evidence</option></select></label><label>Visual localization <select name="visual_localization" required><option>adequate</option><option>inadequate</option><option>ambiguous</option><option>insufficient_evidence</option></select></label><div id="postControls"></div><label>Reason for change <textarea name="reason_for_change"></textarea></label><button>Submit separate post-reveal record</button></form>
<form id="finalForm" class="hidden"><h3>Finalize human review</h3><label>Correction status <select name="corrected_label_status" required><option>no_correction_proposed</option><option>visual_only_not_benchmark_correction</option><option>correction_potentially_defensible_requires_annotation_amendment</option><option>indeterminate</option></select></label><label>Defensibility reason <textarea name="corrected_label_reason" required></textarea></label><label>Comments <textarea name="comments"></textarea></label><button>Finalize through authoritative validator</button></form>
<pre id="status"></pre></section></div>
<script>
const controlNames=['object_present_in_proposed_region','class_appears_correct','box_reasonably_localizes_object','relevant_annotation_appears_missing','nearby_competing_instance','image_evidence_inconclusive'];
function controlsHtml(prefix){return controlNames.map(n=>`<label>${n} <select name="${n}" required><option></option><option>yes</option><option>no</option><option>uncertain</option></select></label>`).join('')};blindControls.innerHTML=controlsHtml('blind');postControls.innerHTML=controlsHtml('post');
let cases=[],i=0,img=new Image(),revealedData=null,drawn=null,start=null;const ctx=canvas.getContext('2d');
function box(b,color,w=3){if(!b)return;ctx.strokeStyle=color;ctx.lineWidth=w;ctx.strokeRect(b[0],b[1],b[2]-b[0],b[3]-b[1])}
function draw(){let c=cases[i];canvas.width=c.image_width;canvas.height=c.image_height;ctx.drawImage(img,0,0);box(c.initial_box_root_xyxy,'red',4);if(drawn)box(drawn,'yellow',4);if(revealedData){revealedData.same_class_gt_boxes_xyxy.forEach(b=>box(b,'lime'));revealedData.nearby_other_class_gt_boxes.forEach(x=>box(x.bbox_xyxy,'cyan',2));box(revealedData.zoom_crop_root_xyxy,'orange');box(revealedData.focused_box_root_xyxy,'magenta',4)}}
function show(){let c=cases[i];revealedData=null;drawn=null;revealed.className='hidden';postForm.className='hidden';finalForm.className='hidden';revealButton.disabled=true;blindForm.className='';position.textContent=` ${i+1}/${cases.length} ${c.case_id}`;query.textContent=`Query: ${c.query}`;blindMeta.textContent=`dimensions=${c.image_width}×${c.image_height} candidate=${c.initial_candidate_id}; independent reviews=${c.stage.independent_review_count}`;img.onload=draw;img.src='/source/'+encodeURIComponent(c.case_id)}
canvas.onpointerdown=e=>{if(!drawBox.checked)return;let r=canvas.getBoundingClientRect();start=[(e.clientX-r.left)*canvas.width/r.width,(e.clientY-r.top)*canvas.height/r.height]};canvas.onpointerup=e=>{if(!start)return;let r=canvas.getBoundingClientRect(),end=[(e.clientX-r.left)*canvas.width/r.width,(e.clientY-r.top)*canvas.height/r.height];drawn=[Math.min(start[0],end[0]),Math.min(start[1],end[1]),Math.max(start[0],end[0]),Math.max(start[1],end[1])];start=null;draw()};
function controlValues(fd){let x={};controlNames.forEach(n=>x[n]=fd.get(n));return x}function ambiguity(c){return {class_identity_ambiguous:c.class_appears_correct==='uncertain'?'yes':'no',localization_ambiguous:c.box_reasonably_localizes_object==='uncertain'?'yes':'no',insufficient_image_evidence:c.image_evidence_inconclusive}}function judgment(v){return v==='yes'?'supported':v==='no'?'unsupported':'ambiguous'}function verification(fd,c){let loc=fd.get('visual_localization');return {object_presence:judgment(c.object_present_in_proposed_region),class_correctness:judgment(c.class_appears_correct),localization_adequacy:loc,evidence_ambiguous:c.image_evidence_inconclusive!=='no',localization_evidence_insufficient:loc==='insufficient_evidence'}}
blindForm.onsubmit=async e=>{e.preventDefault();let c=cases[i],fd=new FormData(blindForm),controls=controlValues(fd),refs=[];if(drawn)refs=[{pixel_xyxy:drawn,image_width:c.image_width,image_height:c.image_height,object_class:c.query,object_identity_note:fd.get('object_identity_note')||'unspecified visual instance',occluded:fd.has('occluded'),truncated:fd.has('truncated'),reviewer_id:fd.get('reviewer_id'),created_at:new Date().toISOString()}];let body={case_id:c.case_id,reviewer_id:fd.get('reviewer_id'),submitted_at:new Date().toISOString(),visual_plausibility:fd.get('visual_plausibility'),visual_localization:fd.get('visual_localization'),ambiguity_controls:ambiguity(controls),visual_verification:verification(fd,controls),legacy_evidence_controls:controls,reference_boxes:refs};let r=await fetch('/api/blind',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});status.textContent=await r.text();if(r.ok){c.stage.blind_first_pass_submitted=true;c.stage.reviewer_id=body.reviewer_id;revealButton.disabled=false;blindForm.className='hidden';loadProgress()}};
resumeButton.onclick=async()=>{let c=cases[i],reviewer=new FormData(blindForm).get('reviewer_id'),body={case_id:c.case_id,reviewer_id:reviewer,submitted_at:new Date().toISOString()};let r=await fetch('/api/resume',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}),text=await r.text();status.textContent=text;if(r.ok){let x=JSON.parse(text);c.stage.reviewer_id=reviewer;blindForm.className='hidden';if(x.gt_revealed){revealedData=x.reveal;revealed.className='';postForm.className=x.post_reveal?'hidden':'';finalForm.className='';draw()}else revealButton.disabled=false}};
revealButton.onclick=async()=>{let c=cases[i],body={case_id:c.case_id,reviewer_id:c.stage.reviewer_id,submitted_at:new Date().toISOString()};let r=await fetch('/api/reveal',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});let text=await r.text();status.textContent=text;if(r.ok){revealedData=JSON.parse(text).reveal;revealed.className='';revealed.textContent=`score=${revealedData.initial_score} H_annotation=${JSON.stringify(revealedData.H_annotation)} best_iou=${revealedData.best_eligible_iou}`;postForm.className='';finalForm.className='';revealButton.disabled=true;draw();loadProgress()}};
postForm.onsubmit=async e=>{e.preventDefault();let c=cases[i],fd=new FormData(postForm),blindFd=new FormData(blindForm),controls=controlValues(fd),refs=[];if(drawn)refs=[{pixel_xyxy:drawn,image_width:c.image_width,image_height:c.image_height,object_class:c.query,object_identity_note:blindFd.get('object_identity_note')||'post-reveal visual instance',occluded:blindFd.has('occluded'),truncated:blindFd.has('truncated'),reviewer_id:c.stage.reviewer_id,created_at:new Date().toISOString()}];let body={case_id:c.case_id,reviewer_id:c.stage.reviewer_id,submitted_at:new Date().toISOString(),visual_plausibility:fd.get('visual_plausibility'),visual_localization:fd.get('visual_localization'),ambiguity_controls:ambiguity(controls),visual_verification:verification(fd,controls),legacy_evidence_controls:controls,reference_boxes:refs,reason_for_change:fd.get('reason_for_change')||''};let r=await fetch('/api/post-reveal',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});status.textContent=await r.text()};
finalForm.onsubmit=async e=>{e.preventDefault();let c=cases[i],fd=new FormData(finalForm),body={case_id:c.case_id,reviewer_id:c.stage.reviewer_id,corrected_label_status:fd.get('corrected_label_status'),corrected_label_reason:fd.get('corrected_label_reason'),comments:fd.get('comments')||''};let r=await fetch('/api/finalize',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});status.textContent=await r.text();if(r.ok)loadProgress()};
prev.onclick=()=>{i=(i+cases.length-1)%cases.length;show()};next.onclick=()=>{i=(i+1)%cases.length;show()};function loadProgress(){fetch('/api/progress').then(r=>r.json()).then(x=>progress.textContent=`Completed ${x.completed_case_count}/${x.queue_case_count}; blind passes ${x.blind_first_pass_count}; outstanding ${x.outstanding_queue_case_count}`)}fetch('/api/cases').then(r=>r.json()).then(x=>{cases=x;show();loadProgress()});
</script></body></html>"""


def serve(output, host, port, sample="all"):
    prior = ROOT / "outputs/bite/phase04b2b4"
    cases = {row["case_id"]: row for row in (
        json.loads(line) for line in (prior / "review_interface/review_cases.jsonl").read_text().splitlines()
    )}
    queue_ids = json.loads((prior / "review_interface/review_queue.json").read_text())["case_ids"]
    if sample == "set-a":
        queue_ids = json.loads((prior / "review_sampling/statistical_review_sample.json").read_text())["case_ids"]
    elif sample == "set-b":
        queue_ids = json.loads((prior / "review_sampling/targeted_review_sample.json").read_text())["case_ids"]
    event_root = output / "review_validation/events"
    completed = prior / "human_adjudications/completed"
    event_root.mkdir(parents=True, exist_ok=True)
    completed.mkdir(parents=True, exist_ok=True)

    def reveal_data(case):
        return {key: case[key] for key in (
            "initial_score", "H_annotation", "same_class_gt_boxes_xyxy",
            "nearby_other_class_gt_boxes", "best_eligible_iou", "zoom_crop_root_xyxy",
            "focused_box_root_xyxy", "focused_score", "diagnostic_primary",
        )}

    def completed_reviews():
        return [json.loads(path.read_text()) for path in sorted(completed.glob("*.json"))]

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status_code, value, content_type="application/json"):
            data = value if isinstance(value, bytes) else (
                value.encode() if isinstance(value, str) else json.dumps(value).encode()
            )
            self.send_response(status_code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _body(self):
            return json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))

        def do_GET(self):
            if self.path == "/":
                return self._send(200, _html(), "text/html; charset=utf-8")
            if self.path == "/api/progress":
                return self._send(200, progress_summary(list(cases.values()), queue_ids, event_root, completed_reviews()))
            if self.path == "/api/cases":
                rows = []
                for case_id in queue_ids:
                    case = cases[case_id]
                    reviewer_events = []
                    for directory in event_root.glob("*"):
                        first = directory / "0001_blind_first_pass.json"
                        if first.is_file():
                            event = json.loads(first.read_text())
                            if event.get("case_id") == case_id:
                                reviewer_events.append((event["reviewer_id"], directory))
                    stage = {
                        "blind_first_pass_submitted": bool(reviewer_events),
                        "gt_revealed": any((directory / "0002_gt_revealed.json").is_file() for _, directory in reviewer_events),
                        "reviewer_id": reviewer_events[0][0] if len(reviewer_events) == 1 else None,
                        "independent_review_count": len(reviewer_events),
                    }
                    rows.append({
                        "case_id": case_id, "source_group_id": case["source_group_id"],
                        "initial_candidate_id": case["initial_candidate_id"], "query": case["query"],
                        "image_width": case["image_width"], "image_height": case["image_height"],
                        "initial_box_root_xyxy": case["initial_box_root_xyxy"],
                        "source_image_sha256": case["source_image_sha256"],
                        "candidate_digest": candidate_digest(case), "stage": stage,
                    })
                return self._send(200, rows)
            if self.path.startswith("/source/"):
                case = cases.get(unquote(self.path[len("/source/"):]))
                if case is None:
                    return self._send(404, "not found", "text/plain")
                source = Path(case["source_image_path"])
                data = source.read_bytes()
                if hashlib.sha256(data).hexdigest() != case["source_image_sha256"]:
                    return self._send(409, "source identity mismatch", "text/plain")
                return self._send(200, data, "image/jpeg")
            return self._send(404, "not found", "text/plain")

        def do_POST(self):
            try:
                body = self._body()
                case = cases[body["case_id"]]
                base = {
                    **body, "schema_version": BLIND_EVENT_VERSION,
                    "protocol_version": ACTIVE_BLIND_PROTOCOL_VERSION, "reviewer_type": "human",
                    "source_group_id": case["source_group_id"],
                    "initial_candidate_id": case["initial_candidate_id"],
                    "source_image_sha256": case["source_image_sha256"],
                    "annotation_sha256": case["annotation_sha256"],
                    "candidate_digest": candidate_digest(case),
                }
                if self.path == "/api/blind":
                    base["event_type"] = "blind_first_pass_submitted"
                    base["independent_second_review_status"] = (
                        "second_or_later_independent_review"
                        if any(
                            (directory / "0001_blind_first_pass.json").is_file()
                            and json.loads((directory / "0001_blind_first_pass.json").read_text()).get("case_id")
                            == case["case_id"]
                            for directory in event_root.glob("*")
                        ) else "primary_review"
                    )
                    saved = append_event(event_root, case, base)
                    return self._send(201, {"status": "BLIND_FIRST_PASS_SAVED", "event": saved})
                chain = load_event_chain(event_root, case, body["reviewer_id"])
                if self.path == "/api/resume":
                    if chain["first_pass"] is None:
                        raise ValueError("No saved blind first pass for this reviewer and case")
                    return self._send(200, {
                        "status": "RESUMED", "blind_first_pass_submitted": True,
                        "gt_revealed": chain["reveal"] is not None,
                        "post_reveal": chain["post_reveal"] is not None,
                        "reveal": reveal_data(case) if chain["reveal"] is not None else None,
                    })
                if self.path == "/api/reveal":
                    base["event_type"] = "gt_revealed"
                    base["blind_event_identity"] = chain["first_pass"]["event_identity"]
                    append_event(event_root, case, base)
                    return self._send(201, {"status": "GT_REVEALED", "reveal": reveal_data(case)})
                if self.path == "/api/post-reveal":
                    base["event_type"] = "post_reveal_judgment"
                    saved = append_event(event_root, case, base)
                    return self._send(201, {"status": "POST_REVEAL_SAVED", "event": saved})
                if self.path == "/api/finalize":
                    selected = chain["post_reveal"] or chain["first_pass"]
                    controls = selected["legacy_evidence_controls"]
                    endpoint = selected["derived_visual_endpoint"]
                    review = {
                        "schema_version": REVIEW_VERSION, "case_id": case["case_id"],
                        "reviewer_id": body["reviewer_id"], "reviewer_type": "human",
                        "reviewed_at": _now(), "protocol_version": PROTOCOL_VERSION,
                        "annotation_sha256": case["annotation_sha256"],
                        "H_visual_review": _visual_label(endpoint, controls), "controls": controls,
                        "applicable_iou_thresholds": ["0.5", "0.75"],
                        "corrected_label_status": body["corrected_label_status"],
                        "corrected_label_reason": body["corrected_label_reason"],
                        "comments": body.get("comments", ""),
                        "blind_protocol_version": chain["first_pass"]["protocol_version"],
                        "blind_event_identity": chain["first_pass"]["event_identity"],
                    }
                    validate_final_completion(review, case, chain)
                    name = hashlib.sha256(
                        f"{review['case_id']}:{review['reviewer_id']}".encode(),
                    ).hexdigest() + ".json"
                    with (completed / name).open("x") as stream:
                        stream.write(json.dumps(review, indent=2, sort_keys=True) + "\n")
                    return self._send(201, {"status": "HUMAN_REVIEW_COMPLETED"})
                return self._send(404, {"status": "NOT_FOUND"})
            except (KeyError, TypeError, ValueError, FileExistsError, json.JSONDecodeError) as error:
                return self._send(400, {"status": "INVALID", "error": str(error)})

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Blind-first review interface: http://{host}:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/bite/phase04c1b"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8115)
    parser.add_argument("--sample", choices=("set-a", "set-b", "all"), default="all")
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("The human review interface is loopback-only")
    serve(args.output.resolve(), args.host, args.port, args.sample)


if __name__ == "__main__":
    main()
