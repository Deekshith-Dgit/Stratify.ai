
"""Evidence-based blind-spot candidate detection for Stratify.AI."""

from typing import Any


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _confidence(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return max(0.0, min(1.0, float(value)))


def detect_blind_spots(profile: Any) -> dict:
    """
    Detect reviewable candidates using explicit profile evidence.
    This is rule-based screening, not a psychological diagnosis.
    """
    if not isinstance(profile, dict):
        profile = {}

    evidence = profile.get("evidence", [])
    goals = profile.get("goals", [])
    constraints = profile.get("constraints", [])
    unknowns = profile.get("unknowns", [])

    if not isinstance(evidence, list):
        evidence = []
    if not isinstance(goals, list):
        goals = []
    if not isinstance(constraints, list):
        constraints = []
    if not isinstance(unknowns, list):
        unknowns = []

    candidates = []

    # Flag potentially conflicting preferences only when both are explicit.
    for item in evidence:
        if not isinstance(item, dict):
            continue

        claim = _text(item.get("claim"))
        normalized = claim.casefold()

        high_income = any(
            phrase in normalized
            for phrase in ("high salary", "high income", "earn a lot")
        )
        limited_hours = any(
            phrase in normalized
            for phrase in (
                "limited working hours",
                "few working hours",
                "work-life balance",
                "don't want long hours",
                "do not want long hours",
            )
        )

        if high_income:
            for other in evidence:
                if not isinstance(other, dict) or other is item:
                    continue

                other_claim = _text(other.get("claim"))
                other_normalized = other_claim.casefold()

                if any(
                    phrase in other_normalized
                    for phrase in (
                        "limited working hours",
                        "few working hours",
                        "work-life balance",
                        "don't want long hours",
                        "do not want long hours",
                    )
                ):
                    candidates.append({
                        "type": "possible_tradeoff",
                        "title": "Compensation and working-hours trade-off",
                        "explanation": (
                            "The profile contains a high-income goal and "
                            "a preference for limited working hours. "
                            "These may be compatible, but the acceptable "
                            "trade-off is not yet specified."
                        ),
                        "evidence": [claim, other_claim],
                        "confidence": min(
                            _confidence(item.get("confidence")),
                            _confidence(other.get("confidence")),
                        ),
                        "status": "needs_clarification",
                        "follow_up": (
                            "What income target and maximum weekly working "
                            "hours would be acceptable to you?"
                        ),
                    })
                    break

    if unknowns:
        candidates.append({
            "type": "missing_information",
            "title": "Important information is still unknown",
            "explanation": (
                "The profile has unanswered questions that may affect "
                "the quality of a future recommendation."
            ),
            "evidence": list(unknowns[:10]),
            "confidence": 1.0,
            "status": "needs_clarification",
            "follow_up": _text(unknowns[0]),
        })

    return {
        "candidates": candidates,
        "candidate_count": len(candidates),
        "profile_complete": len(unknowns) == 0,
        "notice": (
            "Candidates are prompts for clarification, not confirmed "
            "facts or psychological diagnoses."
        ),
    }
