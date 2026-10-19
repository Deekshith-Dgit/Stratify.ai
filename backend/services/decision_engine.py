
"""Explainable multi-criteria decision engine for Stratify.AI."""

from typing import Any


def compare_options(
    options: list[dict],
    criteria: list[dict],
    constraints: list[dict] | None = None,
) -> dict:
    """
    Compare options using user-defined criterion weights and scores.

    Each option:
      {"id": "option_a", "name": "Option A",
       "scores": {"cost": 4, "flexibility": 5}}

    Each criterion:
      {"id": "cost", "name": "Cost", "weight": 0.6,
       "direction": "higher_is_better"}

    Scores and weights range from 0 to 5.
    Hard constraints must be explicitly evaluated by the caller.
    """

    if not isinstance(options, list) or not options:
        raise ValueError("Provide at least one option.")

    if not isinstance(criteria, list) or not criteria:
        raise ValueError("Provide at least one criterion.")

    if constraints is None:
        constraints = []

    if not isinstance(constraints, list):
        raise ValueError("constraints must be a list.")

    seen_options = set()
    normalized_options = []

    for option in options:
        if not isinstance(option, dict):
            raise ValueError("Each option must be an object.")

        option_id = option.get("id")
        name = option.get("name")
        scores = option.get("scores")

        if not isinstance(option_id, str) or not option_id.strip():
            raise ValueError("Every option needs a non-empty id.")

        if option_id in seen_options:
            raise ValueError("Option ids must be unique.")

        if not isinstance(name, str) or not name.strip():
            raise ValueError("Every option needs a name.")

        if not isinstance(scores, dict):
            raise ValueError("Every option needs a scores object.")

        seen_options.add(option_id)
        normalized_options.append({
            "id": option_id,
            "name": name.strip(),
            "scores": scores,
        })

    criterion_ids = set()
    normalized_criteria = []
    total_weight = 0.0

    for criterion in criteria:
        if not isinstance(criterion, dict):
            raise ValueError("Each criterion must be an object.")

        criterion_id = criterion.get("id")
        name = criterion.get("name")
        weight = criterion.get("weight", 1)
        direction = criterion.get("direction", "higher_is_better")

        if not isinstance(criterion_id, str) or not criterion_id.strip():
            raise ValueError("Every criterion needs a non-empty id.")

        if criterion_id in criterion_ids:
            raise ValueError("Criterion ids must be unique.")

        if not isinstance(name, str) or not name.strip():
            raise ValueError("Every criterion needs a name.")

        if (
            isinstance(weight, bool)
            or not isinstance(weight, (int, float))
            or not 0 <= weight <= 5
        ):
            raise ValueError("Criterion weights must be between 0 and 5.")

        if direction not in ("higher_is_better", "lower_is_better"):
            raise ValueError(
                "direction must be higher_is_better or lower_is_better."
            )

        criterion_ids.add(criterion_id)
        total_weight += weight

        normalized_criteria.append({
            "id": criterion_id,
            "name": name.strip(),
            "weight": float(weight),
            "direction": direction,
        })

    if total_weight <= 0:
        raise ValueError("At least one criterion must have positive weight.")

    results = []

    for option in normalized_options:
        weighted_total = 0.0
        used_weight = 0.0
        breakdown = []
        missing_criteria = []

        for criterion in normalized_criteria:
            criterion_id = criterion["id"]
            weight = criterion["weight"]

            raw_score = option["scores"].get(criterion_id)

            if raw_score is None:
                missing_criteria.append(criterion_id)
                continue

            if (
                isinstance(raw_score, bool)
                or not isinstance(raw_score, (int, float))
                or not 0 <= raw_score <= 5
            ):
                raise ValueError(
                    f"Score for {option['id']}/{criterion_id} "
                    "must be between 0 and 5."
                )

            score = float(raw_score)

            if criterion["direction"] == "lower_is_better":
                score = 5.0 - score

            weighted_contribution = score * weight
            weighted_total += weighted_contribution
            used_weight += weight

            breakdown.append({
                "criterion": criterion["name"],
                "original_score": float(raw_score),
                "normalized_score": score,
                "weight": weight,
                "weighted_contribution": weighted_contribution,
            })

        comparable = not missing_criteria

        results.append({
            "id": option["id"],
            "name": option["name"],
            "score": (
                round(weighted_total / used_weight, 3)
                if used_weight > 0 else None
            ),
            "comparable": comparable,
            "missing_criteria": missing_criteria,
            "breakdown": breakdown,
        })

    # Do not rank incomplete options against complete ones.
    ranked = sorted(
        [item for item in results if item["comparable"]],
        key=lambda item: item["score"],
        reverse=True,
    )

    return {
        "ranked_options": ranked,
        "unranked_options": [
            item for item in results if not item["comparable"]
        ],
        "method": "weighted_multi_criteria_score",
        "score_scale": "0–5; higher is better after direction adjustment",
        "constraints": constraints,
        "constraint_notice": (
            "Constraints are recorded but not enforced by this function. "
            "Check hard constraints separately before recommending an option."
        ),
        "limitations": [
            "Scores are only as reliable as the evidence behind them.",
            "Weights represent supplied preferences, not objective truth.",
            "A ranking is not a guarantee of the best real-world outcome.",
        ],
    }
