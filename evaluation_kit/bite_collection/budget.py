"""Logical collection costs, distinct from hypothetical agent path costs."""


def path_cost(prefix_cost, branch_cost):
    if min(prefix_cost, branch_cost) < 0:
        raise ValueError("Logical costs cannot be negative")
    return prefix_cost + branch_cost


def experimental_expenditure(branch_records):
    return sum(record["branch_cost"] for record in branch_records)


def check_budget(path, remaining):
    estimated = sum(action.get("estimated_logical_cost", 1) for action in path)
    return {"eligible": remaining is None or estimated <= remaining,
            "estimated_branch_cost": estimated,
            "reason": None if remaining is None or estimated <= remaining else "insufficient_branch_budget"}
