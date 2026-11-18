"""Evaluator-only ground-truth resolution and post-run evaluation.

This module is deliberately separate from the inference path: nothing in
``openvlharness.multi_agent`` imports it, runners never call it, and the Studio
server uses it only behind a dedicated, evaluator-authorized endpoint.

Release policy
--------------
* No authoritative source for the run              -> ``NOT_AVAILABLE``
* Run not in a terminal state                      -> ``SEALED`` (value withheld)
* Terminal, but caller lacks evaluator credentials -> ``ACCESS_DENIED`` (value withheld)
* Terminal and authorized, source verified         -> ``AVAILABLE`` (value + provenance)
* Terminal and authorized, source inconsistent     -> ``REFERENCE_ERROR``

Authoritative sources are (1) the official dataset row named by the run's
label-free ``inputs/dataset_task.json`` (loaded through the repository dataset
loader and verified against the recorded row identity and question), or (2) an
evaluator-written reference artifact in the evaluator-only reference directory
(used by deterministic test fixtures, clearly labelled as such). Worker or
coordinator outputs, tool results, and filenames are never consulted.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from .replay import read_json, safe_run_dir

SCHEMA = "studio.reference.v1"
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "BUDGET_EXHAUSTED"}
LABELS = {
    "NOT_AVAILABLE": "No reference label available.",
    "SEALED": "Ground truth sealed until completion.",
    "ACCESS_DENIED": "Reference access not permitted.",
    "REFERENCE_ERROR": "Reference could not be verified.",
}
RELEASE_POLICY = "released_after_terminal_state_to_evaluator_only"
COUNT_RULE = "fsc147_parse_count_exact_match"
COUNT_NOTE = (
    "Official annotated instance count for this row; annotations are not guaranteed "
    "to be an exhaustive visual truth."
)
# Dataset loader classes whose deterministic evaluation rule is known here.
_RULES = {"FSC147Dataset": (COUNT_RULE, "integer_count")}


def _terminal(run: Path) -> str | None:
    state = (read_json(run / "run_state.json", {}) or {}).get("status")
    final = read_json(run / "final_result.json", None)
    if state in TERMINAL and isinstance(final, dict):
        return state
    return None


def _source(run: Path, reference_dir: Path | None) -> dict[str, Any] | None:
    if reference_dir is not None:
        path = (reference_dir / f"{run.name}.json").resolve()
        if path.parent == reference_dir.resolve() and path.is_file() and not path.is_symlink():
            return {"kind": "evaluation_artifact", "path": path}
    task = read_json(run / "inputs" / "dataset_task.json", None)
    if isinstance(task, dict) and task.get("dataset") and task.get("row_position") is not None:
        return {"kind": "dataset_row", "task": task}
    return None


def evaluate(prediction: Any, reference: Any, rule: str | None) -> dict[str, Any] | None:
    """Deterministic correctness under the benchmark's own normalization rule."""
    if rule != COUNT_RULE:
        return None
    from evaluation_kit.dataset.utils.fsc147 import parse_count

    try:
        expected = int(str(reference).strip())
    except ValueError:
        return {"rule": rule, "valid": False, "reason": "Reference is not an integer."}
    parsed = parse_count(prediction) if prediction is not None else None
    return {
        "rule": rule,
        "valid": True,
        "prediction": prediction,
        "parsed_prediction": parsed,
        "reference": expected,
        "correct": parsed is not None and parsed == expected,
        "parse_failed": parsed is None,
        "absolute_error": abs(parsed - expected) if parsed is not None else None,
    }


class ReferenceResolver:
    """Resolve and cache references; datasets are loaded lazily and once."""

    def __init__(self, reference_dir: Path | None = None, dataset_loader=None) -> None:
        self.reference_dir = reference_dir
        self._loader = dataset_loader
        self._datasets: dict[str, Any] = {}
        self._cache: dict[tuple[str, float], dict[str, Any]] = {}
        self._lock = threading.Lock()

    def _dataset(self, name: str):
        with self._lock:
            if name not in self._datasets:
                loader = self._loader
                if loader is None:
                    from evaluation_kit.dataset import build_dataset as loader
                self._datasets[name] = loader(name)
            return self._datasets[name]

    def _resolve_dataset_row(self, task: dict[str, Any]) -> dict[str, Any]:
        name = str(task["dataset"])
        provenance = {
            "dataset": name,
            "split": name.rsplit("_", 1)[-1] if "_" in name else None,
            "row_position": task.get("row_position"),
            "dataset_index": task.get("dataset_index"),
            "reference_source": f"Official {name} annotation (repository dataset loader)",
        }
        try:
            dataset = self._dataset(name)
        except Exception as exc:  # noqa: BLE001 - loader failures become explicit errors
            return {"error": f"Dataset could not be loaded: {type(exc).__name__}", "provenance": provenance}
        if dataset is None or getattr(dataset, "data", None) is None:
            return {"error": "Dataset is not prepared locally.", "provenance": provenance}
        position = int(task["row_position"])
        if not 0 <= position < len(dataset.data):
            return {"error": "Recorded row position is outside the dataset.", "provenance": provenance}
        row = dataset.data.iloc[position]
        if str(row.get("index", position)) != str(task.get("dataset_index")):
            return {"error": "Dataset row identity does not match the recorded index.", "provenance": provenance}
        question = task.get("question")
        if question is not None and str(row.get("question", "")).strip() != str(question).strip():
            return {"error": "Dataset question does not match the recorded task.", "provenance": provenance}
        if "answer" not in row or row.get("answer") is None:
            return {"error": "The dataset row has no answer field.", "provenance": provenance}
        rule, answer_type = _RULES.get(type(dataset).__name__, (None, "unknown"))
        provenance.update(
            {
                "question_type": answer_type,
                "normalization_rule": rule,
                "note": COUNT_NOTE if answer_type == "integer_count" else None,
            }
        )
        return {"value": str(row["answer"]), "rule": rule, "provenance": provenance}

    def _resolve_artifact(self, path: Path, run_id: str) -> dict[str, Any]:
        data = read_json(path, None)
        if not isinstance(data, dict) or data.get("schema_version") != SCHEMA:
            return {"error": "Evaluation artifact is malformed.", "provenance": {"reference_source": "evaluation artifact"}}
        provenance = {
            key: data.get(key)
            for key in ("dataset", "split", "row", "reference_source", "note")
        }
        provenance["question_type"] = data.get("answer_type")
        provenance["normalization_rule"] = data.get("normalization_rule")
        if data.get("run_id") != run_id:
            return {"error": "Evaluation artifact belongs to another run.", "provenance": provenance}
        if data.get("reference") is None:
            return {"error": "Evaluation artifact has no reference value.", "provenance": provenance}
        if data.get("answer_type") == "integer_count":
            provenance.setdefault("note", COUNT_NOTE)
        return {"value": str(data["reference"]), "rule": data.get("normalization_rule"), "provenance": provenance}

    def status(self, root: Path, run_id: str, *, evaluator: bool) -> dict[str, Any]:
        run = safe_run_dir(root, run_id)
        base = {
            "schema_version": SCHEMA,
            "run_id": run_id,
            "release_policy": RELEASE_POLICY,
            "evaluator_access": evaluator,
        }
        source = _source(run, self.reference_dir)
        if source is None:
            return {**base, "state": "NOT_AVAILABLE", "label": LABELS["NOT_AVAILABLE"]}
        # Non-sensitive provenance (dataset and row identity) is shown even while sealed.
        public = (
            {
                "dataset": source["task"].get("dataset"),
                "row_position": source["task"].get("row_position"),
                "dataset_index": source["task"].get("dataset_index"),
            }
            if source["kind"] == "dataset_row"
            else {"reference_source": "evaluation artifact"}
        )
        terminal = _terminal(run)
        if terminal is None:
            return {**base, "state": "SEALED", "label": LABELS["SEALED"], "provenance": public}
        if not evaluator:
            return {**base, "state": "ACCESS_DENIED", "label": LABELS["ACCESS_DENIED"], "provenance": public}
        stamp_path = source.get("path") or (run / "inputs" / "dataset_task.json")
        try:
            stamp = (stamp_path.stat().st_mtime + (run / "final_result.json").stat().st_mtime)
        except OSError:
            stamp = 0.0
        key = (str(run), stamp)
        with self._lock:
            cached = self._cache.get(key)
        if cached is None:
            resolved = (
                self._resolve_artifact(source["path"], run_id)
                if source["kind"] == "evaluation_artifact"
                else self._resolve_dataset_row(source["task"])
            )
            final = read_json(run / "final_result.json", {}) or {}
            if "error" in resolved:
                cached = {
                    "state": "REFERENCE_ERROR",
                    "label": LABELS["REFERENCE_ERROR"],
                    "error": resolved["error"],
                    "provenance": resolved.get("provenance", public),
                }
            else:
                cached = {
                    "state": "AVAILABLE",
                    "label": f"Ground truth: {resolved['value']}",
                    "value": resolved["value"],
                    "provenance": {**resolved["provenance"], "reference_value": resolved["value"]},
                    "run_status": terminal,
                    "evaluation": evaluate(final.get("final_answer"), resolved["value"], resolved.get("rule"))
                    if terminal == "COMPLETED"
                    else None,
                }
            with self._lock:
                self._cache[key] = cached
        return {**base, **cached}

