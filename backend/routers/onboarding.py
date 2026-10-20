import json
import logging
import math
import sqlite3
import uuid

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from adaptive_engine import generate_next_question
from database import get_connection
from routers.auth import get_current_user


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/onboarding",
    tags=["Onboarding"],
)

GENERATION_TIMEOUT_SECONDS = 90
MAX_ONBOARDING_QUESTIONS = 12
MAX_QUESTION_OPTIONS = 12
MAX_OPTION_TEXT_LENGTH = 200


FIRST_QUESTION = {
    "status": "ask",
    "question": {
        "id": "role",
        "text": "Which best describes you right now?",
        "type": "single_choice",
        "options": [
            {
                "label": "Student",
                "value": "student",
            },
            {
                "label": "Working professional",
                "value": "professional",
            },
            {
                "label": "Other",
                "value": "other",
            },
        ],
    },
    "reason": (
        "Your current situation helps personalize "
        "the assessment."
    ),
    "profile_updates": [],
    "unknowns": [],
}


class AnswerInput(BaseModel):
    session_id: uuid.UUID
    question_id: str = Field(
        min_length=1,
        max_length=100,
    )
    answer: str = Field(
        min_length=1,
        max_length=5000,
    )

    @field_validator("question_id", "answer")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError(
                "This field cannot be empty."
            )

        return value


def ensure_onboarding_schema() -> None:
    """
    Apply additive database changes without deleting
    existing user data.
    """
    with get_connection() as db:
        columns = {
            row["name"]
            for row in db.execute(
                "PRAGMA table_info(onboarding_sessions)"
            ).fetchall()
        }

        if "current_question_json" not in columns:
            db.execute(
                """
                ALTER TABLE onboarding_sessions
                ADD COLUMN current_question_json TEXT
                """
            )

        if "generation_started_at" not in columns:
            db.execute(
                """
                ALTER TABLE onboarding_sessions
                ADD COLUMN generation_started_at TEXT
                """
            )

        answer_columns = {
            row["name"]
            for row in db.execute(
                "PRAGMA table_info(onboarding_answers)"
            ).fetchall()
        }
        if "question_text" not in answer_columns:
            db.execute(
                """
                ALTER TABLE onboarding_answers
                ADD COLUMN question_text TEXT NOT NULL DEFAULT ''
                """
            )

        duplicates = db.execute(
            """
            SELECT 1
            FROM onboarding_answers
            GROUP BY session_id, question_id
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        ).fetchone()

        if duplicates:
            logger.warning(
                "Duplicate historical onboarding answers found; "
                "skipping unique index."
            )
        else:
            db.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS
                ux_onboarding_session_question
                ON onboarding_answers(session_id, question_id)
                """
            )


def parse_json(
    value: Any,
    fallback: Any,
) -> Any:
    try:
        return json.loads(value) if value else fallback
    except (TypeError, json.JSONDecodeError):
        return fallback


def get_owned_session(
    db,
    session_id: str,
    user_id: str,
):
    session = db.execute(
        """
        SELECT *
        FROM onboarding_sessions
        WHERE id = ? AND user_id = ?
        """,
        (session_id, user_id),
    ).fetchone()

    if session is None:
        raise HTTPException(
            status_code=404,
            detail="Onboarding session not found.",
        )

    return session


def get_profile(
    db,
    user_id: str,
) -> dict:
    user = db.execute(
        """
        SELECT profile_json
        FROM users
        WHERE id = ?
        """,
        (user_id,),
    ).fetchone()

    if user is None:
        raise HTTPException(
            status_code=404,
            detail="User not found.",
        )

    profile = parse_json(
        user["profile_json"],
        {},
    )

    return profile if isinstance(profile, dict) else {}


def get_session_answers(
    db,
    session_id: str,
) -> list[dict]:
    rows = db.execute(
        """
        SELECT question_id, question_text, answer
        FROM onboarding_answers
        WHERE session_id = ?
        ORDER BY id ASC
        """,
        (session_id,),
    ).fetchall()

    return [
        {
            "question_id": row["question_id"],
            "question_text": row["question_text"],
            "answer": row["answer"],
        }
        for row in rows
    ]


def get_session_progress(
    db,
    session_id: str,
    complete: bool = False,
) -> dict:
    answered = db.execute(
        """
        SELECT COUNT(*) AS answer_count
        FROM onboarding_answers
        WHERE session_id = ?
        """,
        (session_id,),
    ).fetchone()["answer_count"]

    return {
        "completed_questions": answered,
        "total_questions": MAX_ONBOARDING_QUESTIONS,
        "completion_percent": (
            100
            if complete
            else round(answered * 100 / MAX_ONBOARDING_QUESTIONS)
        ),
    }


def get_completed_response(
    db,
    session_id: str,
    user_id: str,
) -> dict:
    return {
        "status": "complete",
        "question": None,
        "reason": (
            "The adaptive assessment is complete."
        ),
        "profile": get_profile(db, user_id),
        "answers": get_session_answers(
            db,
            session_id,
        ),
        "progress": get_session_progress(
            db,
            session_id,
            complete=True,
        ),
    }


def _valid_options(
    question: dict,
) -> list[dict]:
    options = question.get("options")

    if (
        not isinstance(options, list)
        or not 2 <= len(options) <= MAX_QUESTION_OPTIONS
    ):
        raise HTTPException(
            status_code=500,
            detail=(
                "This question's options are invalid. "
                "Please retry the question."
            ),
        )

    seen_labels: set[str] = set()
    seen_values: set[str] = set()
    cleaned = []

    for option in options:
        if not isinstance(option, dict):
            raise HTTPException(
                status_code=500,
                detail="This question's options are invalid.",
            )

        label = option.get("label")
        value = option.get("value")

        if (
            not isinstance(label, str)
            or not isinstance(value, str)
        ):
            raise HTTPException(
                status_code=500,
                detail="This question's options are invalid.",
            )

        label = label.strip()
        value = value.strip()

        if (
            not label
            or not value
            or len(label) > MAX_OPTION_TEXT_LENGTH
            or len(value) > MAX_OPTION_TEXT_LENGTH
        ):
            raise HTTPException(
                status_code=500,
                detail="This question's options are invalid.",
            )

        label_key = label.casefold()
        value_key = value.casefold()

        if (
            label_key in seen_labels
            or value_key in seen_values
        ):
            raise HTTPException(
                status_code=500,
                detail=(
                    "This question contains duplicate options. "
                    "Please retry the question."
                ),
            )

        seen_labels.add(label_key)
        seen_values.add(value_key)

        cleaned.append(
            {
                "label": label,
                "value": value,
            }
        )

    return cleaned


def validate_answer(
    question: dict,
    answer: str,
) -> str:
    """Validate an answer against the stored question."""

    if not isinstance(question, dict):
        raise HTTPException(
            status_code=500,
            detail=(
                "The pending question is invalid. "
                "Please refresh and try again."
            ),
        )

    if not isinstance(answer, str):
        raise HTTPException(
            status_code=422,
            detail=(
                "Please enter an answer in the "
                "expected format."
            ),
        )

    answer = answer.strip()

    if not answer:
        raise HTTPException(
            status_code=422,
            detail=(
                "Please provide an answer before continuing."
            ),
        )

    question_type = question.get("type")

    if question_type == "text":
        if len(answer) > 5000:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Your answer must be 5,000 "
                    "characters or fewer."
                ),
            )

        return answer

    if question_type in {
        "single_choice",
        "multi_choice",
    }:
        options = _valid_options(question)

        valid_values = {
            option["value"].casefold(): option["value"]
            for option in options
        }

        if question_type == "single_choice":
            chosen = answer

            if chosen.casefold() not in valid_values:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "Please select one of the "
                        "available options."
                    ),
                )

            return valid_values[chosen.casefold()]

        try:
            selected = json.loads(answer)
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Select one or more options in list "
                    'format, e.g. ["option_a", "option_b"].'
                ),
            )

        if not isinstance(selected, list) or not selected:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Please select at least one option."
                ),
            )

        if any(
            not isinstance(item, str) or not item.strip()
            for item in selected
        ):
            raise HTTPException(
                status_code=422,
                detail="The selected options are invalid.",
            )

        normalized = []
        seen = set()

        for item in selected:
            key = item.strip().casefold()

            if key not in valid_values:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "One or more selected options "
                        "are unavailable."
                    ),
                )

            if key in seen:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "The same option cannot be "
                        "selected more than once."
                    ),
                )

            seen.add(key)
            normalized.append(valid_values[key])

        return json.dumps(
            normalized,
            ensure_ascii=False,
        )

    if question_type == "number":
        try:
            number = float(answer)
        except (ValueError, OverflowError):
            raise HTTPException(
                status_code=422,
                detail=(
                    "Please enter a valid number, "
                    "such as 16 or 3.5."
                ),
            )

        if not math.isfinite(number):
            raise HTTPException(
                status_code=422,
                detail="Please enter a finite number.",
            )

        minimum = question.get("min")
        maximum = question.get("max")

        if minimum is not None and number < minimum:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Please enter a number of at least "
                    f"{minimum}."
                ),
            )

        if maximum is not None and number > maximum:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Please enter a number no greater "
                    f"than {maximum}."
                ),
            )

        return answer

    raise HTTPException(
        status_code=500,
        detail=(
            "This question uses an unsupported answer type."
        ),
    )
    logger.error(
        "Unsupported pending question type: %r",
        question_type,
    )

    raise HTTPException(
        status_code=500,
        detail=(
            "This question has an unsupported format. "
            "Please try again."
        ),
    )


def validate_generated_result(
    result: Any,
    answered_ids: set[str],
) -> dict:
    """
    Validate and normalize adaptive-engine output
    before saving it to the database.
    """
    if not isinstance(result, dict):
        raise ValueError(
            "AI output must be a JSON object."
        )

    status = result.get("status")

    if status not in {"ask", "complete"}:
        raise ValueError("Invalid AI status.")

    reason = result.get("reason", "")

    if (
        not isinstance(reason, str)
        or len(reason) > 2000
    ):
        raise ValueError("Invalid AI reason.")

    unknowns = result.get("unknowns", [])

    if (
        not isinstance(unknowns, list)
        or len(unknowns) > 50
    ):
        raise ValueError("Invalid unknowns list.")

    if status == "complete":
        return {
            "status": "complete",
            "question": None,
            "reason": reason,
            "profile_updates": [],
            "unknowns": unknowns,
        }

    question = result.get("question")

    if not isinstance(question, dict):
        raise ValueError(
            "AI did not return a valid question."
        )

    question_id = question.get("id")
    question_text = question.get("text")
    question_type = question.get("type")

    if (
        not isinstance(question_id, str)
        or not question_id.strip()
        or len(question_id) > 100
    ):
        raise ValueError("Invalid question ID.")

    question_id = question_id.strip()

    if question_id in answered_ids:
        raise ValueError(
            "AI generated a question that was already answered."
        )

    if (
        not isinstance(question_text, str)
        or not question_text.strip()
        or len(question_text) > 2000
    ):
        raise ValueError("Invalid question text.")

    if question_type not in {
        "text",
        "single_choice",
        "multi_choice",
        "number",
    }:
        raise ValueError("Unsupported question type.")

    clean_question = {
        "id": question_id,
        "text": question_text.strip(),
        "type": question_type,
    }

    if question_type in {
        "single_choice",
        "multi_choice",
    }:
        options = question.get("options")

        if (
            not isinstance(options, list)
            or not 2 <= len(options) <= MAX_QUESTION_OPTIONS
        ):
            raise ValueError(
                "Choice questions need 2–12 options."
            )

        clean_options = []
        seen_labels: set[str] = set()
        seen_values: set[str] = set()

        for option in options:
            if not isinstance(option, dict):
                raise ValueError("Invalid choice option.")

            label = option.get("label")
            value = option.get("value")

            if (
                not isinstance(label, str)
                or not isinstance(value, str)
            ):
                raise ValueError(
                    "Invalid option label or value."
                )

            label = label.strip()
            value = value.strip()

            if (
                not label
                or not value
                or len(label) > MAX_OPTION_TEXT_LENGTH
                or len(value) > MAX_OPTION_TEXT_LENGTH
            ):
                raise ValueError(
                    "Invalid option label or value."
                )

            label_key = label.casefold()
            value_key = value.casefold()

            if label_key in seen_labels:
                raise ValueError(
                    "Duplicate option labels."
                )

            if value_key in seen_values:
                raise ValueError(
                    "Duplicate option values."
                )

            seen_labels.add(label_key)
            seen_values.add(value_key)

            clean_options.append(
                {
                    "label": label,
                    "value": value,
                }
            )

        clean_question["options"] = clean_options

    if question_type == "number":
        for bound in ("min", "max"):
            if (
                bound in question
                and question[bound] is not None
            ):
                value = question[bound]

                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                ):
                    raise ValueError(
                        f"Invalid numeric {bound} bound."
                    )

                clean_question[bound] = value

        minimum = clean_question.get("min")
        maximum = clean_question.get("max")

        if (
            minimum is not None
            and maximum is not None
            and minimum > maximum
        ):
            raise ValueError(
                "Numeric question minimum exceeds maximum."
            )

    return {
        "status": "ask",
        "question": clean_question,
        "reason": reason,
        "profile_updates": [],
        "unknowns": unknowns,
    }


def _mark_complete(
    db,
    session_id: str,
    user_id: str,
) -> dict:
    db.execute(
        """
        UPDATE onboarding_sessions
        SET status = 'completed',
            current_question_json = NULL,
            generation_started_at = NULL
        WHERE id = ? AND user_id = ?
        """,
        (session_id, user_id),
    )

    return get_completed_response(
        db,
        session_id,
        user_id,
    )


@router.post("/start")
def start_onboarding(
    user=Depends(get_current_user),
):
    ensure_onboarding_schema()

    session_id = str(uuid.uuid4())

    with get_connection() as db:
        db.execute("BEGIN IMMEDIATE")

        db.execute(
            """
            INSERT INTO onboarding_sessions (
                id,
                user_id,
                status,
                created_at,
                current_question_json,
                generation_started_at
            )
            VALUES (?, ?, ?, ?, ?, NULL)
            """,
            (
                session_id,
                user["id"],
                "in_progress",
                datetime.now(timezone.utc).isoformat(),
                json.dumps(
                    FIRST_QUESTION,
                    ensure_ascii=False,
                ),
            ),
        )

        progress = get_session_progress(db, session_id)

    return {
        "session_id": session_id,
        **FIRST_QUESTION,
        "progress": progress,
    }


@router.post("/answer")
def submit_answer(
    data: AnswerInput,
    user=Depends(get_current_user),
):
    ensure_onboarding_schema()

    session_id = str(data.session_id)
    user_id = user["id"]

    with get_connection() as db:
        db.execute("BEGIN IMMEDIATE")

        session = get_owned_session(
            db,
            session_id,
            user_id,
        )

        if session["status"] != "in_progress":
            raise HTTPException(
                status_code=409,
                detail=(
                    "This session is not accepting answers "
                    "right now. Call GET /onboarding/next "
                    "to check its state."
                ),
            )

        pending = parse_json(
            session["current_question_json"],
            None,
        )

        if (
            not isinstance(pending, dict)
            or not isinstance(pending.get("question"), dict)
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "There is no valid pending question "
                    "for this session."
                ),
            )

        question = pending["question"]

        if data.question_id != question.get("id"):
            raise HTTPException(
                status_code=409,
                detail="This is not the current question.",
            )

        clean_answer = validate_answer(
            question,
            data.answer,
        )

        try:
            db.execute(
                """
                INSERT INTO onboarding_answers (
                    session_id,
                    question_id,
                    question_text,
                    answer,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    data.question_id,
                    question["text"],
                    clean_answer,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(
                status_code=409,
                detail=(
                    "An answer for this question "
                    "already exists."
                ),
            )

        if data.question_id == "role":
            profile = get_profile(db, user_id)
            profile["role"] = clean_answer

            db.execute(
                """
                UPDATE users
                SET profile_json = ?
                WHERE id = ?
                """,
                (
                    json.dumps(
                        profile,
                        ensure_ascii=False,
                    ),
                    user_id,
                ),
            )

        db.execute(
            """
            UPDATE onboarding_sessions
            SET status = 'awaiting_adaptive_engine',
                current_question_json = NULL,
                generation_started_at = NULL
            WHERE id = ? AND user_id = ?
            """,
            (session_id, user_id),
        )

    # The answer is saved before calling the AI engine.
    # If generation fails, GET /next can retry it.
    result = generate_and_store_next(
        session_id,
        user_id,
    )

    with get_connection() as db:
        progress = get_session_progress(
            db,
            session_id,
            complete=result.get("status") == "complete",
        )

    return {
        "session_id": session_id,
        "answer_saved": True,
        **result,
        "progress": progress,
    }


def generate_and_store_next(
    session_id: str,
    user_id: str,
) -> dict:
    now = datetime.now(timezone.utc)

    with get_connection() as db:
        db.execute("BEGIN IMMEDIATE")

        session = get_owned_session(
            db,
            session_id,
            user_id,
        )

        if session["status"] == "completed":
            return get_completed_response(
                db,
                session_id,
                user_id,
            )

        if session["status"] == "in_progress":
            current = parse_json(
                session["current_question_json"],
                None,
            )

            if isinstance(current, dict):
                return {
                    **current,
                    "progress": get_session_progress(
                        db,
                        session_id,
                    ),
                }

            raise HTTPException(
                status_code=409,
                detail="No current question is available.",
            )

        answers = get_session_answers(
            db,
            session_id,
        )

        # Hard limit: do not generate more questions
        # after the configured number of answers.
        if len(answers) >= MAX_ONBOARDING_QUESTIONS:
            return _mark_complete(
                db,
                session_id,
                user_id,
            )

        if session["status"] == "generating":
            started_at = session["generation_started_at"]

            try:
                started = datetime.fromisoformat(
                    started_at
                )

                if started.tzinfo is None:
                    started = started.replace(
                        tzinfo=timezone.utc
                    )

            except (TypeError, ValueError):
                started = now - timedelta(
                    seconds=GENERATION_TIMEOUT_SECONDS + 1
                )

            if (
                now - started
            ).total_seconds() <= GENERATION_TIMEOUT_SECONDS:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "A question is already being generated. "
                        "Try again shortly."
                    ),
                )

            db.execute(
                """
                UPDATE onboarding_sessions
                SET status = 'awaiting_adaptive_engine',
                    generation_started_at = NULL
                WHERE id = ? AND user_id = ?
                """,
                (session_id, user_id),
            )

        elif session["status"] != "awaiting_adaptive_engine":
            raise HTTPException(
                status_code=409,
                detail=(
                    "This session cannot generate a question "
                    "in its current state."
                ),
            )

        claimed = db.execute(
            """
            UPDATE onboarding_sessions
            SET status = 'generating',
                generation_started_at = ?
            WHERE id = ?
              AND user_id = ?
              AND status = 'awaiting_adaptive_engine'
            """,
            (
                now.isoformat(),
                session_id,
                user_id,
            ),
        )

        if claimed.rowcount != 1:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Could not claim this session "
                    "for question generation."
                ),
            )

        profile = get_profile(db, user_id)

    try:
        raw_result = generate_next_question(
            profile,
            answers,
        )

        result = validate_generated_result(
            raw_result,
            {
                item["question_id"]
                for item in answers
            },
        )

    except Exception as exc:
        with get_connection() as db:
            db.execute(
                """
                UPDATE onboarding_sessions
                SET status = 'awaiting_adaptive_engine',
                    generation_started_at = NULL
                WHERE id = ?
                  AND user_id = ?
                  AND status = 'generating'
                """,
                (session_id, user_id),
            )

        logger.warning(
            "Adaptive question generation failed for "
            "session %s (%s).",
            session_id,
            type(exc).__name__,
        )

        raise HTTPException(
            status_code=502,
            detail=(
                "The adaptive engine could not generate "
                "the next question. Your answer was saved; "
                "call GET /onboarding/next to retry."
            ),
        )

    with get_connection() as db:
        db.execute("BEGIN IMMEDIATE")

        session = get_owned_session(
            db,
            session_id,
            user_id,
        )

        if session["status"] != "generating":
            if session["status"] == "in_progress":
                current = parse_json(
                    session["current_question_json"],
                    None,
                )

                if isinstance(current, dict):
                    return current

            if session["status"] == "completed":
                return get_completed_response(
                    db,
                    session_id,
                    user_id,
                )

            raise HTTPException(
                status_code=409,
                detail=(
                    "The session state changed during "
                    "generation. Call /next."
                ),
            )

        if result["status"] == "complete":
            db.execute(
                """
                UPDATE onboarding_sessions
                SET status = 'completed',
                    current_question_json = NULL,
                    generation_started_at = NULL
                WHERE id = ? AND user_id = ?
                """,
                (session_id, user_id),
            )

            return get_completed_response(
                db,
                session_id,
                user_id,
            )

        db.execute(
            """
            UPDATE onboarding_sessions
            SET status = 'in_progress',
                current_question_json = ?,
                generation_started_at = NULL
            WHERE id = ? AND user_id = ?
            """,
            (
                json.dumps(
                    result,
                    ensure_ascii=False,
                ),
                session_id,
                user_id,
            ),
        )

    return result


@router.get("/next")
def get_next_question(
    session_id: uuid.UUID = Query(...),
    user=Depends(get_current_user),
):
    ensure_onboarding_schema()

    session_id = str(session_id)
    user_id = user["id"]

    with get_connection() as db:
        session = get_owned_session(
            db,
            session_id,
            user_id,
        )

        if session["status"] == "in_progress":
            current = parse_json(
                session["current_question_json"],
                None,
            )

            if isinstance(current, dict):
                return current

            raise HTTPException(
                status_code=409,
                detail="No pending question is stored.",
            )

        if session["status"] == "completed":
            return get_completed_response(
                db,
                session_id,
                user_id,
            )

        if session["status"] == "generating":
            started_at = session["generation_started_at"]

            try:
                started = datetime.fromisoformat(
                    started_at
                )

                if started.tzinfo is None:
                    started = started.replace(
                        tzinfo=timezone.utc
                    )

            except (TypeError, ValueError):
                started = datetime.min.replace(
                    tzinfo=timezone.utc
                )

            elapsed = (
                datetime.now(timezone.utc) - started
            ).total_seconds()

            if elapsed <= GENERATION_TIMEOUT_SECONDS:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Question generation is still "
                        "in progress. Try again shortly."
                    ),
                )

    # Recover interrupted generation using the same session.
    result = generate_and_store_next(
        session_id,
        user_id,
    )
    with get_connection() as db:
        progress = get_session_progress(
            db,
            session_id,
            complete=result.get("status") == "complete",
        )

    return {
        **result,
        "progress": progress,
    }


@router.get("/profile")
def get_onboarding_profile(
    user=Depends(get_current_user),
):
    ensure_onboarding_schema()

    user_id = user["id"]

    with get_connection() as db:
        profile = get_profile(
            db,
            user_id,
        )

        sessions = db.execute(
            """
            SELECT id, status, created_at
            FROM onboarding_sessions
            WHERE user_id = ?
            ORDER BY created_at DESC
            """,
            (user_id,),
        ).fetchall()

        return {
            "profile": profile,
            "sessions": [
                {
                    "session_id": session["id"],
                    "status": session["status"],
                    "created_at": session["created_at"],
                }
                for session in sessions
            ],
        }