"""Prespecified coverage and seeded randomized path selection."""

import copy
import random


def deterministic_coverage(eligible, *, limit=None, design_id="deterministic_coverage.v1"):
    selected = eligible[:limit] if limit is not None else eligible
    return [{"path": copy.deepcopy(path), "selection_design": design_id,
             "selection_probability": 1.0, "path_draw_probability": 1.0,
             "selection_steps": [{"eligible_count": len(eligible), "conditional_probability": 1.0,
                                   "selected_path_name": path["path_name"]}], "selection_seed": None}
            for path in selected]


def randomized_selection(eligible, *, count=1, seed, design_id="uniform_without_replacement.v1"):
    if count < 0 or count > len(eligible):
        raise ValueError("Randomized selection count exceeds the eligible path set")
    generator = random.Random(seed)
    pool = list(range(len(eligible)))
    chosen = []
    for draw in range(count):
        position = generator.randrange(len(pool))
        chosen.append((pool.pop(position), len(pool) + 1, draw))
    inclusion = count / len(eligible) if eligible else None
    result = []
    for index, population, draw in chosen:
        result.append({"path": copy.deepcopy(eligible[index]), "selection_design": design_id,
                       "selection_probability": inclusion,
                       "path_draw_probability": 1 / population,
                       "selection_steps": [{"draw_index": draw, "eligible_remaining": population,
                                            "conditional_probability": 1 / population,
                                            "selected_path_name": eligible[index]["path_name"]}],
                       "selection_seed": seed, "rng": "python.random.Random(MT19937)"})
    return result
