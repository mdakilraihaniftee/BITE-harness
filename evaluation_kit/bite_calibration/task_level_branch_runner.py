"""Gated, resumable final-answer runner for the Phase 4C-1G counting probe.

Order per (task, branch) unit:

1. verify the frozen task;
2. render the branch input from stored evidence (and, for B2/B3, the validated
   semantic observation);
3. persist the branch input and its request digest;
4. dispatch exactly one request;
5. persist the raw response and the parsed answer;
6. seal the unit with content digests.

Labels are not reachable from this path. ``finalize_outcomes`` hashes the
complete GT-free outcome table. Only then does ``build_count_labels`` open the
official annotations, and it refuses unless the finalization record is intact.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from evaluation_kit.bite_collection.integrity import StageEventLedger
from evaluation_kit.bite_collection.persistence import atomic_json
from evaluation_kit.bite_collection.resume import ResumeLedger, file_digest
from openvlharness.services.models import ModelAdapter, load_profile

from .branch_evidence_renderer import RENDERER_SHA256, redacted_messages, render_branch
from .semantic_observation_schema import canonical_sha256
from .semantic_pilot_analysis import validate_observations
from .semantic_region_action import MODEL_ALIAS, _is_timeout
from .task_level_probe_protocol import (
    BRANCH_EVIDENCE,
    BRANCHES,
    FINAL_ANSWER_OPTIONS,
    FINAL_ANSWER_SEED,
    PARSER_SHA256,
    PROMPT_SHA256,
    _leaked_keys,
    parse_count,
    validate_branch_authorization,
    verify_task_manifest,
)

RUN_VERSION = "bite.phase04c1g_branch_run.v1"
CANARY_MAX_TASKS = 5
CONSECUTIVE_FAILURE_LIMIT = 3
OUTCOME_TABLE_VERSION = "bite.phase04c1g_raw_outcome_table.v1"
LABEL_TABLE_VERSION = "bite.phase04c1g_count_labels.v1"


def build_adapter(base, *, key="", timeout=120, requester=None):
    """Existing ModelAdapter pinned to the frozen alias; no transport retries, so one
    logical dispatch is exactly one physical request."""
    return ModelAdapter({"alias": MODEL_ALIAS, "base": base, "key": key, "timeout": timeout, "retry": 0,
                         **FINAL_ANSWER_OPTIONS}, requester=requester)


def unit_id(task, branch):
    return f"{task['task_id']}:{branch}"


# ------------------------------------------------------------ semantic evidence

def _semantic_state_dir(run_dir, case_id):
    return Path(run_dir) / "states" / case_id.replace(":", "_")


def semantic_dispatch_count(run_dir):
    """Dispatched semantic requests in the 4C-1F run: complete plus partial case dirs."""
    states = Path(run_dir) / "states"
    return sum(1 for path in states.iterdir() if path.is_dir() and any(path.iterdir())) if states.is_dir() else 0


def load_semantic_observations(run_dir, manifest, semantic_manifest, *, require_live):
    """Content-verified semantic observations for every task, or an error."""
    observations = {}
    for task in manifest["tasks"]:
        state_dir = _semantic_state_dir(run_dir, task["semantic_case_id"])
        marker = state_dir / "raw_completion.json"
        if not marker.is_file():
            raise ValueError(f"Semantic observation not finalized for {task['state_id']}")
        record = json.loads(marker.read_text())
        for relative, expected in record["content_sha256"].items():
            if file_digest(state_dir / relative) != expected:
                raise ValueError(f"Semantic observation content changed for {task['state_id']}")
        observations[task["semantic_case_id"]] = json.loads((state_dir / "semantic_observation.json").read_text())
    summary = validate_observations(list(observations.values()), semantic_manifest, require_live=require_live)
    if not summary["complete"]:
        raise ValueError("Semantic observations do not cover the frozen population")
    return observations, summary


# ------------------------------------------------------------------- execution

def _unit_status(ledger, uid):
    state_dir = ledger.state_dir(uid)
    marker = state_dir / "raw_completion.json"
    if not marker.is_file():
        return "partial" if state_dir.exists() and any(state_dir.iterdir()) else "pending"
    record = json.loads(marker.read_text())
    if record.get("configuration_sha256") != ledger.config_digest:
        return "corrupt"
    for relative, expected in record["content_sha256"].items():
        path = state_dir / relative
        if not path.is_file() or file_digest(path) != expected:
            return "corrupt"
    return "complete"


def run_branches(manifest, adapter, output_dir, *, root, mode, branches, semantic_run_dir=None,
                 semantic_manifest=None, semantic_observations=None, authorization=None, resume=False,
                 canary_tasks=None, clock=time.perf_counter, now=None):
    """Dispatch pending (task, branch) units once each.

    ``mode`` is ``mock_dry_run`` (requires an injected requester) or ``live``
    (requires a researcher authorization bound to the exact run). The final-answer
    cap and the phase-total cap (semantic + final answers) are cumulative across
    canary, main and resumed invocations.
    """
    verify_task_manifest(manifest)
    branches = list(branches)
    if not branches or not set(branches) <= set(BRANCHES):
        raise ValueError("Unknown branch requested")
    if canary_tasks is not None and not (isinstance(canary_tasks, int) and 0 < canary_tasks <= CANARY_MAX_TASKS):
        raise ValueError(f"A canary covers between 1 and {CANARY_MAX_TASKS} tasks")
    authorization_digest = None
    if mode == "mock_dry_run":
        if adapter.requester is None:
            raise PermissionError("Dry run requires an injected local requester; refusing a network client")
        cap = len(branches) * len(manifest["tasks"])
        total_cap = None
    elif mode == "live":
        binding = validate_branch_authorization(authorization, manifest, adapter, output_dir, root=root, now=now)
        if not set(branches) <= set(binding["branches"]):
            raise PermissionError("Requested branches exceed the authorized branch set")
        cap, total_cap = binding["dispatch_cap"], binding["phase_total_dispatch_cap"]
        authorization_digest = canonical_sha256(authorization)
    else:
        raise ValueError(f"Unknown run mode: {mode}")
    needs_semantic = any("semantic" in BRANCH_EVIDENCE[b] for b in branches)
    semantic_dispatches = 0
    if mode == "live":
        if semantic_observations is not None:
            raise PermissionError("Live runs load semantic observations from the authorized run directory only")
        if semantic_run_dir is None or (Path(root) / str(authorization["semantic_run_dir"])).resolve() != (
                Path(semantic_run_dir).resolve()):
            raise PermissionError("Semantic run directory differs from the authorized one")
    if semantic_run_dir is not None:
        semantic_dispatches = semantic_dispatch_count(semantic_run_dir)
        if needs_semantic:
            if semantic_manifest is None:
                raise ValueError("The frozen semantic manifest is required to validate semantic observations")
            semantic_observations, _ = load_semantic_observations(
                semantic_run_dir, manifest, semantic_manifest, require_live=mode == "live")
    if needs_semantic and not semantic_observations:
        raise ValueError("Branches B2/B3 require finalized semantic observations; none supplied")
    if mode == "mock_dry_run":
        total_cap = cap + semantic_dispatches
    configuration = {
        "schema_version": RUN_VERSION, "mode": mode, "task_manifest_sha256": manifest["manifest_sha256"],
        "prompt_sha256": PROMPT_SHA256, "parser_sha256": PARSER_SHA256, "renderer_sha256": RENDERER_SHA256,
        "model_id": adapter.model, "endpoint": adapter.endpoint, "options": FINAL_ANSWER_OPTIONS,
        "seed": FINAL_ANSWER_SEED, "branches": branches, "dispatch_cap": cap, "phase_total_dispatch_cap": total_cap,
        "authorization_sha256": authorization_digest,
    }
    ledger = ResumeLedger(output_dir, configuration, resume=resume)
    units = [(task, branch) for task in manifest["tasks"] for branch in branches]
    statuses = {unit_id(t, b): _unit_status(ledger, unit_id(t, b)) for t, b in units}
    blocked = sorted(uid for uid, status in statuses.items() if status in {"partial", "corrupt"})
    if blocked:
        raise RuntimeError(f"Unit {blocked[0]} is {statuses[blocked[0]]}; inspect before any new execution")
    prior = sum(status == "complete" for status in statuses.values())
    budget = min(cap - prior, total_cap - semantic_dispatches - prior)
    if budget < 0:
        raise PermissionError("Cumulative dispatches already exceed an authorized cap")
    if canary_tasks is not None:
        pending_tasks = []
        for task, branch in units:
            if statuses[unit_id(task, branch)] == "pending" and task["task_id"] not in pending_tasks:
                pending_tasks.append(task["task_id"])
        allowed_tasks = set(pending_tasks[:canary_tasks])
    else:
        allowed_tasks = None
    summary = {"run_phase": "canary" if canary_tasks else "main", "complete_before_run": prior,
               "semantic_dispatches_counted": semantic_dispatches, "dispatch_cap": cap,
               "phase_total_dispatch_cap": total_cap, "dispatched": 0, "skipped_cap": 0, "statuses": {},
               "offline_labels_accessed": False}
    dispatched = 0
    consecutive = 0
    for task, branch in units:
        uid = unit_id(task, branch)
        if statuses[uid] == "complete" or (allowed_tasks is not None and task["task_id"] not in allowed_tasks):
            continue
        if dispatched >= budget:
            summary["skipped_cap"] += 1
            continue
        state_dir = ledger.state_dir(uid)
        events = StageEventLedger(state_dir / "stage_events.jsonl")
        observation = semantic_observations.get(task["semantic_case_id"]) if semantic_observations else None
        messages, rendered = render_branch(task, branch, root=root,
                                           semantic_observation=observation if "semantic" in BRANCH_EVIDENCE[branch] else None)
        payload = adapter.payload(messages, options=dict(FINAL_ANSWER_OPTIONS), seed=FINAL_ANSWER_SEED)
        payload_redacted = redacted_messages(payload)
        input_path = state_dir / "branch_input.json"
        atomic_json(input_path, {
            "schema_version": "bite.phase04c1g_branch_input.v1", "unit_id": uid, "task_id": task["task_id"],
            "state_id": task["state_id"], "source_group_id": task["source_group_id"], "branch": branch,
            "rendered": rendered, "payload_redacted": payload_redacted,
            "payload_redacted_sha256": canonical_sha256(payload_redacted),
        })
        events.append("branch_input_persisted", {"branch_input_sha256": file_digest(input_path), "mode": mode,
                                                 "authorization_sha256": authorization_digest})
        started_utc = datetime.now(timezone.utc).isoformat()
        started = clock()
        response, text, error_type, error_detail = None, None, None, None
        try:
            response = adapter.request(messages, options=dict(FINAL_ANSWER_OPTIONS), seed=FINAL_ANSWER_SEED)
            text, _, _ = adapter.parse(response, 0)
            status, count, detail = parse_count(text)
        except Exception as error:  # noqa: BLE001 - recorded as an invalid answer, never retried
            status = "timeout" if _is_timeout(error) else "execution_failure"
            count, detail = None, None
            error_type, error_detail = type(error).__name__, str(error)[:500]
        latency_ms = (clock() - started) * 1000.0
        dispatched += 1
        served = response.get("model") if isinstance(response, dict) else None
        response_path = state_dir / "raw_response.json"
        answer_path = state_dir / "final_answer.json"
        atomic_json(response_path, {"schema_version": "bite.phase04c1g_raw_response.v1", "response": response})
        atomic_json(answer_path, {
            "schema_version": "bite.phase04c1g_final_answer.v1", "unit_id": uid, "task_id": task["task_id"],
            "branch": branch, "mode": mode, "mock": mode == "mock_dry_run", "raw_text": text,
            "response_status": status, "parsed_count": count, "parse_detail": detail,
            "error_type": error_type, "error_detail": error_detail, "latency_ms": latency_ms,
            "token_usage": response.get("usage") if isinstance(response, dict) else None,
            "served_model_reported": served, "model_id": adapter.model, "started_utc": started_utc,
            "finished_utc": datetime.now(timezone.utc).isoformat(), "cumulative_dispatch_index": prior + dispatched - 1,
            "physical_requests_issued": 1, "authorization_sha256": authorization_digest,
            "offline_labels_accessed": False,
        })
        raw = ledger.mark_raw(uid, [input_path, response_path, answer_path],
                              {"mode": mode, "branch": branch, "response_status": status})
        events.append("raw_finalized", {"raw_completion_sha256": file_digest(state_dir / "raw_completion.json"),
                                        "content_sha256": raw["content_sha256"]})
        summary["statuses"][status] = summary["statuses"].get(status, 0) + 1
        if mode == "live" and served is not None and served != adapter.model:
            _halt(output_dir, summary, dispatched, ledger, f"server reported model {served!r}")
        consecutive = consecutive + 1 if status in {"timeout", "execution_failure"} else 0
        if consecutive >= CONSECUTIVE_FAILURE_LIMIT:
            _halt(output_dir, summary, dispatched, ledger, f"{consecutive} consecutive transport failures")
    summary["dispatched"] = dispatched
    summary["configuration_sha256"] = ledger.config_digest
    atomic_json(Path(output_dir) / f"run_summary_{summary['run_phase']}_{int(time.time())}.json", summary)
    return summary


def _halt(output_dir, summary, dispatched, ledger, reason):
    summary.update(dispatched=dispatched, configuration_sha256=ledger.config_digest, halted=True, halt_reason=reason)
    atomic_json(Path(output_dir) / "run_summary_halted.json", summary)
    raise RuntimeError(f"Branch run halted after persisting the current unit: {reason}")


# ---------------------------------------------------------------- finalization

def finalize_outcomes(manifest, run_dir, finalized_dir, *, branches=BRANCHES, require_live=True):
    """Hash the complete GT-free outcome table. Refuses incomplete or mixed runs."""
    verify_task_manifest(manifest)
    if (Path(finalized_dir) / "finalization.json").exists():
        raise FileExistsError("Outcome table already finalized; finalization is immutable (use load_finalized)")
    configuration = json.loads((Path(run_dir) / "run_configuration.json").read_text())
    config_digest = configuration["configuration_sha256"]
    rows = []
    for task in manifest["tasks"]:
        for branch in branches:
            state_dir = Path(run_dir) / "states" / unit_id(task, branch).replace(":", "_")
            marker = state_dir / "raw_completion.json"
            if not marker.is_file():
                raise ValueError(f"Unit not complete: {unit_id(task, branch)}")
            record = json.loads(marker.read_text())
            if record["configuration_sha256"] != config_digest:
                raise ValueError("Unit belongs to a different run configuration")
            for relative, expected in record["content_sha256"].items():
                if file_digest(state_dir / relative) != expected:
                    raise ValueError(f"Unit content changed: {unit_id(task, branch)}")
            answer = json.loads((state_dir / "final_answer.json").read_text())
            if require_live and (answer["mock"] or answer["mode"] != "live"):
                raise ValueError("Primary finalization accepts live answers only")
            branch_input = json.loads((state_dir / "branch_input.json").read_text())
            usage = answer.get("token_usage") or {}
            rows.append({
                "task_id": task["task_id"], "state_id": task["state_id"], "source_group_id": task["source_group_id"],
                "query": task["query"], "branch": branch, "response_status": answer["response_status"],
                "parsed_count": answer["parsed_count"], "latency_ms": answer["latency_ms"],
                "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens"),
                "served_model_reported": answer["served_model_reported"],
                "messages_sha256": branch_input["rendered"]["messages_sha256"],
                "evidence_characters": branch_input["rendered"]["evidence_characters"],
                "image_count": branch_input["rendered"]["image_count"],
            })
    if _leaked_keys(rows):
        raise ValueError("Raw outcome table carries GT marker keys")
    finalized_dir = Path(finalized_dir)
    table_path = finalized_dir / "raw_outcome_table.jsonl"
    table_path.parent.mkdir(parents=True, exist_ok=True)
    with table_path.open("w") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
    statuses = Counter((row["branch"], row["response_status"]) for row in rows)
    record = {
        "schema_version": OUTCOME_TABLE_VERSION, "task_manifest_sha256": manifest["manifest_sha256"],
        "run_configuration_sha256": config_digest, "branches": list(branches), "row_count": len(rows),
        "table_sha256": file_digest(table_path), "status_counts": {f"{b}:{s}": n for (b, s), n in sorted(statuses.items())},
        "finalized_utc": datetime.now(timezone.utc).isoformat(), "offline_labels_accessed": False,
    }
    atomic_json(finalized_dir / "finalization.json", record)
    StageEventLedger(finalized_dir / "stage_events.jsonl").append(
        "raw_outcome_table_finalized", {"table_sha256": record["table_sha256"],
                                        "finalization_sha256": file_digest(finalized_dir / "finalization.json")})
    return record, rows


def verify_finalization(finalized_dir):
    finalized_dir = Path(finalized_dir)
    record = json.loads((finalized_dir / "finalization.json").read_text())
    if file_digest(finalized_dir / "raw_outcome_table.jsonl") != record["table_sha256"]:
        raise ValueError("Raw outcome table changed after finalization")
    events = [json.loads(line) for line in (finalized_dir / "stage_events.jsonl").read_text().splitlines() if line]
    if not events or events[0]["event"] != "raw_outcome_table_finalized":
        raise ValueError("Finalization event missing")
    if events[0]["evidence"]["finalization_sha256"] != file_digest(finalized_dir / "finalization.json"):
        raise ValueError("Finalization record changed after its event")
    return record


def load_finalized(finalized_dir):
    record = verify_finalization(finalized_dir)
    rows = [json.loads(line) for line in (Path(finalized_dir) / "raw_outcome_table.jsonl").read_text().splitlines()
            if line.strip()]
    return record, rows


def load_count_labels(labels_dir, finalized_dir):
    """Previously written labels, verified against their event chain and the finalized table."""
    record = verify_finalization(finalized_dir)
    labels_dir = Path(labels_dir)
    events = [json.loads(line) for line in (labels_dir / "stage_events.jsonl").read_text().splitlines() if line]
    written = [e for e in events if e["event"] == "labels_written"]
    if len(written) != 1 or written[0]["evidence"]["finalization_table_sha256"] != record["table_sha256"]:
        raise ValueError("Label event chain does not reference the finalized table")
    if file_digest(labels_dir / "count_labels.jsonl") != written[0]["evidence"]["count_labels_sha256"]:
        raise ValueError("Count labels changed after they were written")
    return [json.loads(line) for line in (labels_dir / "count_labels.jsonl").read_text().splitlines() if line]


def official_count(ground_truth, query):
    """Number of official annotations whose category name equals the query."""
    ids = {c["id"] for c in ground_truth.categories if str(c["name"]).strip().casefold() == query.casefold()}
    if len(ids) != 1:
        raise ValueError(f"Expected exactly one annotation category named {query!r}")
    matched = [a for a in ground_truth.annotations if a["category_id"] in ids]
    return {"official_count": len(matched), "crowd_annotations": sum(bool(a.get("iscrowd")) for a in matched),
            "dropped_invalid_annotations_in_image": len(ground_truth.dropped)}


def build_count_labels(manifest, finalized_dir, labels_dir, *, load_ground_truth):
    """Open official annotations only after a verified finalization.

    ``load_ground_truth(source_entry_id)`` returns an object with ``categories``,
    ``annotations`` and ``dropped`` (``matching.GroundTruth``).
    """
    record = verify_finalization(finalized_dir)
    if record["task_manifest_sha256"] != manifest["manifest_sha256"]:
        raise ValueError("Finalized table belongs to a different task manifest")
    labels_dir = Path(labels_dir)
    if (labels_dir / "count_labels.jsonl").exists():
        raise FileExistsError("Count labels already written; use load_count_labels")
    events = StageEventLedger(labels_dir / "stage_events.jsonl")
    events.append("label_join_started", {"finalization_table_sha256": record["table_sha256"]})
    rows = []
    cache = {}
    for task in manifest["tasks"]:
        entry = task["source_entry_id"]
        if entry not in cache:
            cache[entry] = load_ground_truth(entry)
        rows.append({"schema_version": LABEL_TABLE_VERSION, "task_id": task["task_id"], "state_id": task["state_id"],
                     "source_group_id": task["source_group_id"], "query": task["query"],
                     **official_count(cache[entry], task["query"])})
    path = labels_dir / "count_labels.jsonl"
    with path.open("w") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
    events.append("labels_written", {"count_labels_sha256": file_digest(path),
                                     "finalization_table_sha256": record["table_sha256"]})
    return rows


def join_outcomes(manifest, outcome_rows, label_rows):
    """One analysis row per task: features, official count, per-branch outcomes."""
    labels = {row["task_id"]: row for row in label_rows}
    by_task = {}
    for row in outcome_rows:
        by_task.setdefault(row["task_id"], {})[row["branch"]] = row
    joined = []
    for task in manifest["tasks"]:
        label = labels[task["task_id"]]
        branches = {}
        for branch, row in sorted(by_task[task["task_id"]].items()):
            valid = row["response_status"] == "valid"
            branches[branch] = {
                "status": row["response_status"], "count": row["parsed_count"], "valid": valid,
                "correct": int(valid and row["parsed_count"] == label["official_count"]),
                "presence_correct": int(valid and (row["parsed_count"] > 0) == (label["official_count"] > 0)),
                "latency_ms": row["latency_ms"], "prompt_tokens": row["prompt_tokens"],
                "completion_tokens": row["completion_tokens"], "evidence_characters": row["evidence_characters"],
            }
        joined.append({"task_id": task["task_id"], "state_id": task["state_id"],
                       "source_group_id": task["source_group_id"], "query": task["query"],
                       "official_count": label["official_count"], "features": task["precall_features"],
                       "branches": branches})
    return joined


def served_model_id():
    return load_profile(MODEL_ALIAS)["model_id"]
