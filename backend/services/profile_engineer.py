
"""Shared, explainable user-profile utilities for Stratify.AI."""

from datetime import datetime, timezone
from typing import Any


PROFILE_VERSION = 1

DEFAULT_PROFILE = {
    "schema_version": PROFILE_VERSION,
    "role": None,
    "goals": [],
    "constraints": [],
    "preferences": {},
    "evidence": [],
    "unknowns": [],
    "blind_spots": [],
    "updated_at": None,
}


def _clean_text(value: Any, max_length: int = 500) -> str | None:
    if not isinstance(value, str):
        return None

    value = value.strip()
    if not value or len(value) > max_length:
        return None

    return value


def normalize_profile(profile: Any) -> dict:
    """Return a safe, consistent profile without discarding valid fields."""
    source = profile if isinstance(profile, dict) else {}
    result = {**DEFAULT_PROFILE, **source}

    for field in (
        "goals",
        "constraints",
        "evidence",
        "unknowns",
        "blind_spots",
    ):
        if not isinstance(result.get(field), list):
            result[field] = []

    if not isinstance(result.get("preferences"), dict):
        result["preferences"] = {}

    result["schema_version"] = PROFILE_VERSION
    return result


def add_evidence(
    profile: Any,
    *,
    claim: str,
    source: str,
    confidence: float = 0.8,
) -> dict:
    """Add a traceable observation; confidence is not a probability of truth."""
    result = normalize_profile(profile)

    clean_claim = _clean_text(claim)
    clean_source = _clean_text(source, 100)

    if clean_claim is None or clean_source is None:
        raise ValueError("claim and source must be non-empty text.")

    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ValueError("confidence must be a number between 0 and 1.")

    if not 0 <= confidence <= 1:
        raise ValueError("confidence must be between 0 and 1.")

    result["evidence"].append({
        "claim": clean_claim,
        "source": clean_source,
        "confidence": float(confidence),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    })

    result["updated_at"] = datetime.now(timezone.utc).isoformat()
    return result


def add_unknown(profile: Any, question: str) -> dict:
    """Track information that is still needed for a decision."""
    result = normalize_profile(profile)
    clean_question = _clean_text(question)

    if clean_question is None:
        raise ValueError("question must be non-empty text.")

    if clean_question not in result["unknowns"]:
        result["unknowns"].append(clean_question)

    result["updated_at"] = datetime.now(timezone.utc).isoformat()
    return result


def add_personal_memories(profile: Any, memories: list[str]) -> dict:
    """Persist explicit personal context without duplicating existing notes."""
    result = normalize_profile(profile)
    if not isinstance(memories, list):
        raise ValueError("memories must be a list.")

    existing = result.get("personal_memories", [])
    if not isinstance(existing, list):
        existing = []
    cleaned = []
    seen = set()
    for memory in [*existing, *memories]:
        clean_memory = _clean_text(memory)
        if clean_memory is None:
            if memory in (None, ""):
                continue
            raise ValueError("Each personal memory must be non-empty text.")
        key = clean_memory.casefold()
        if key not in seen:
            cleaned.append(clean_memory)
            seen.add(key)

    result["personal_memories"] = cleaned
    if cleaned != existing:
        result["updated_at"] = datetime.now(timezone.utc).isoformat()
    return result


def add_blind_spot_candidate(
    profile: Any,
    *,
    title: str,
    evidence: list,
    explanation: str,
    confidence: float,
    follow_up: str,
) -> dict:
    """Store a candidate for clarification, not a confirmed psychological fact."""
    result = normalize_profile(profile)

    title = _clean_text(title)
    explanation = _clean_text(explanation)
    follow_up = _clean_text(follow_up)

    if not title or not explanation or not follow_up:
        raise ValueError("title, explanation and follow_up are required.")

    if not isinstance(evidence, list) or not evidence:
        raise ValueError("At least one supporting evidence item is required.")

    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0 <= confidence <= 1
    ):
        raise ValueError("confidence must be between 0 and 1.")

    result["blind_spots"].append({
        "title": title,
        "explanation": explanation,
        "evidence": evidence,
        "confidence": float(confidence),
        "status": "needs_clarification",
        "follow_up": follow_up,
    })

    result["updated_at"] = datetime.now(timezone.utc).isoformat()
    return result
