
from services.decision_engine import compare_options
from services.roadmap_engine import generate_roadmap


def test_decision_engine_ranks_options():
    result = compare_options(
        options=[
            {"id": "a", "name": "Option A", "scores": {"cost": 5}},
            {"id": "b", "name": "Option B", "scores": {"cost": 2}},
        ],
        criteria=[
            {
                "id": "cost",
                "name": "Cost",
                "weight": 1,
                "direction": "higher_is_better",
            }
        ],
    )

    assert result["ranked_options"][0]["id"] == "a"


def test_roadmap_engine_accepts_valid_plan():
    result = generate_roadmap(
        goal="Learn Python",
        steps=[
            {
                "id": "step1",
                "title": "Learn basics",
                "description": "Study variables and loops",
                "outcome": "Write simple programs",
                "duration_days": 3,
            }
        ],
    )

    assert result
    assert isinstance(result, dict)

from services.blindspot_engine import detect_blind_spots


def test_blindspot_detects_income_and_working_hours_tradeoff():
    profile = {
        "evidence": [
            {
                "claim": "I want a high salary",
                "confidence": 0.9,
            },
            {
                "claim": "I want work-life balance",
                "confidence": 0.7,
            },
        ]
    }

    result = detect_blind_spots(profile)

    assert result["candidate_count"] == 1
    candidate = result["candidates"][0]
    assert candidate["type"] == "possible_tradeoff"
    assert candidate["status"] == "needs_clarification"
    assert candidate["confidence"] == 0.7
    assert len(candidate["evidence"]) == 2


def test_blindspot_detects_missing_information():
    profile = {
        "unknowns": [
            "What is your budget?",
            "What is your target career?",
        ]
    }

    result = detect_blind_spots(profile)

    assert result["candidate_count"] == 1
    candidate = result["candidates"][0]
    assert candidate["type"] == "missing_information"
    assert candidate["evidence"] == profile["unknowns"]
    assert candidate["follow_up"] == "What is your budget?"
    assert result["profile_complete"] is False


def test_blindspot_returns_no_candidates_for_complete_neutral_profile():
    result = detect_blind_spots({
        "evidence": [],
        "goals": [],
        "constraints": [],
        "unknowns": [],
    })

    assert result["candidates"] == []
    assert result["candidate_count"] == 0
    assert result["profile_complete"] is True


def test_blindspot_handles_invalid_profile_and_confidence():
    result = detect_blind_spots(None)

    assert result["candidates"] == []
    assert result["candidate_count"] == 0
    assert result["profile_complete"] is True

    result = detect_blind_spots({
        "evidence": [
            {"claim": "I want a high income", "confidence": 5},
            {"claim": "I want limited working hours", "confidence": -1},
        ]
    })

    assert result["candidate_count"] == 1
    assert result["candidates"][0]["confidence"] == 0.0
