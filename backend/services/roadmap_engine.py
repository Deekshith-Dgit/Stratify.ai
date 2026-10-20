
"""Generate structured, explainable action roadmaps for Stratify.AI."""

from datetime import date, timedelta
from typing import Any


def generate_roadmap(
    goal: str,
    steps: list[dict],
    *,
    start_date: str | None = None,
    constraints: list[str] | None = None,
) -> dict:
    """
    Build a structured roadmap from explicitly supplied steps.

    This function organizes steps; it does not invent expert advice.
    Each step needs: title, description, outcome.
    Optional fields: duration_days, dependencies, priority.
    """
    if not isinstance(goal, str) or not goal.strip():
        raise ValueError("goal must be non-empty text.")

    if len(goal) > 500:
        raise ValueError("goal must be 500 characters or fewer.")

    if not isinstance(steps, list) or not steps:
        raise ValueError("Provide at least one roadmap step.")

    if len(steps) > 50:
        raise ValueError("A roadmap can contain at most 50 steps.")

    if start_date is None:
        start = date.today()
    else:
        try:
            start = date.fromisoformat(start_date)
        except (TypeError, ValueError):
            raise ValueError("start_date must use YYYY-MM-DD format.")

    if constraints is None:
        constraints = []

    if not isinstance(constraints, list) or not all(
        isinstance(item, str) for item in constraints
    ):
        raise ValueError("constraints must be a list of strings.")

    normalized = []
    seen_ids = set()

    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            raise ValueError("Each step must be an object.")

        title = step.get("title")
        description = step.get("description")
        outcome = step.get("outcome")

        for field, value in (
            ("title", title),
            ("description", description),
            ("outcome", outcome),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"Step {index} requires a non-empty {field}."
                )

        duration = step.get("duration_days", 7)
        if (
            isinstance(duration, bool)
            or not isinstance(duration, int)
            or not 1 <= duration <= 365
        ):
            raise ValueError(
                f"Step {index} duration_days must be between 1 and 365."
            )

        step_id = step.get("id", f"step_{index}")
        if not isinstance(step_id, str) or not step_id.strip():
            raise ValueError("Step ids must be non-empty strings.")

        if step_id in seen_ids:
            raise ValueError("Step ids must be unique.")
        seen_ids.add(step_id)

        dependencies = step.get("dependencies", [])
        if not isinstance(dependencies, list) or not all(
            isinstance(dep, str) for dep in dependencies
        ):
            raise ValueError("dependencies must be a list of step ids.")

        priority = step.get("priority", "normal")
        if priority not in ("low", "normal", "high"):
            raise ValueError("priority must be low, normal, or high.")

        normalized.append({
            "id": step_id,
            "title": title.strip(),
            "description": description.strip(),
            "outcome": outcome.strip(),
            "duration_days": duration,
            "dependencies": dependencies,
            "priority": priority,
        })

    for step in normalized:
        unknown = set(step["dependencies"]) - seen_ids
        if unknown:
            raise ValueError(
                f"Step {step['id']} has unknown dependencies: "
                f"{sorted(unknown)}"
            )

        if step["id"] in step["dependencies"]:
            raise ValueError("A step cannot depend on itself.")

    # Ensure dependency order is valid; cycles would make the roadmap unusable.
    by_id = {step["id"]: step for step in normalized}
    visiting = set()
    visited = set()

    def visit(step_id: str) -> None:
        if step_id in visiting:
            raise ValueError("Roadmap dependencies contain a cycle.")
        if step_id in visited:
            return

        visiting.add(step_id)
        for dependency in by_id[step_id]["dependencies"]:
            visit(dependency)
        visiting.remove(step_id)
        visited.add(step_id)

    for step in normalized:
        visit(step["id"])

    # Schedule each step after its dependencies have finished.
    finish_days: dict[str, int] = {}

    def finish_day(step_id: str) -> int:
        if step_id in finish_days:
            return finish_days[step_id]

        step = by_id[step_id]
        dependency_finish = max(
            (finish_day(dep) for dep in step["dependencies"]),
            default=0,
        )
        finish_days[step_id] = (
            dependency_finish + step["duration_days"]
        )
        return finish_days[step_id]

    scheduled = []
    for step in normalized:
        end_offset = finish_day(step["id"])
        start_offset = end_offset - step["duration_days"]

        scheduled.append({
            **step,
            "start_date": (
                start + timedelta(days=start_offset)
            ).isoformat(),
            "target_date": (
                start + timedelta(days=end_offset - 1)
            ).isoformat(),
        })

    total_days = max(finish_days.values(), default=0)

    return {
        "goal": goal.strip(),
        "start_date": start.isoformat(),
        "target_completion_date": (
            start + timedelta(days=total_days - 1)
        ).isoformat(),
        "estimated_duration_days": total_days,
        "constraints": constraints,
        "steps": scheduled,
        "explanation": (
            "Dates are estimates derived from step durations and "
            "dependencies. Review them against the user's real schedule."
        ),
    }
