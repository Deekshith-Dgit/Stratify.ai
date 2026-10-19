
import json
import logging
import math
import sqlite3
import uuid
from pydantic import BaseModel, Field, field_validator
from datetime import datetime, timezone, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from database import get_connection
from routers.auth import get_current_user
from adaptive_engine import generate_next_question


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/onboarding", tags=["Onboarding"])

GENERATION_TIMEOUT_SECONDS = 90


# --------------------------------------------------
# 1. INITIAL QUESTION
# --------------------------------------------------

FIRST_QUESTION = {
    "status": "ask",
    "question": {
        "id": "role",
        "text": "Which best describes you right now?",
        "type": "single_choice",
        "options": [
            {"label": "Student", "value": "student"},
            {
                "label": "Working professional",
                "value": "professional",
            },
            {"label": "Other", "value": "other"},
        ],
    },
    "reason": "Your current situation helps personalize the assessment.",
    "profile_updates": [],
    "unknowns": [],
}


# --------------------------------------------------
# 2. REQUEST MODELS
# --------------------------------------------------


class AnswerInput(BaseModel):
    session_id: uuid.UUID
    question_id: str = Field(min_length=1, max_length=100)
    answer: str = Field(min_length=1, max_length=5000)

    @field_validator("question_id", "answer")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be empty.")
        return value

# --------------------------------------------------
# 3. DATABASE COMPATIBILITY / MIGRATION
# --------------------------------------------------

def ensure_onboarding_schema():
    """
    Add columns required by this onboarding implementation
    without deleting existing users or onboarding data.
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

        # Add duplicate-answer protection to existing databases.
        duplicates = db.execute(
            """
            SELECT session_id, question_id, COUNT(*) AS total
            FROM onboarding_answers
            GROUP BY session_id, question_id
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        ).fetchone()

        if duplicates:
            logger.warning(
                "Existing duplicate onboarding answers detected. "
                "Unique index was not created."
            )
        else:
            db.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS
                ux_onboarding_session_question
                ON onboarding_answers(session_id, question_id)
                """
            )


# --------------------------------------------------
# 4. HELPERS
# --------------------------------------------------

def parse_json(value, fallback):
    try:
        return json.loads(value) if value else fallback
    except (TypeError, json.JSONDecodeError):
        return fallback


def get_owned_session(db, session_id, user_id):
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


def get_profile(db, user_id):
    user = db.execute(
        "SELECT profile_json FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()

    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")

    profile = parse_json(user["profile_json"], {})

    if not isinstance(profile, dict):
        profile = {}

    return profile


def get_session_answers(db, session_id):
    rows = db.execute(
        """
        SELECT question_id, answer
        FROM onboarding_answers
        WHERE session_id = ?
        ORDER BY id ASC
        """,
        (session_id,),
    ).fetchall()

    return [
        {
            "question_id": row["question_id"],
            "answer": row["answer"],
        }
        for row in rows
    ]


def get_completed_response(db, session_id, user_id):
    profile = get_profile(db, user_id)
    answers = get_session_answers(db, session_id)

    return {
        "status": "complete",
        "question": None,
        "reason": "The adaptive assessment is complete.",
        "profile": profile,
        "answers": answers,
    }


def validate_answer(question, answer):
    """Validate and normalize an answer against the stored pending question."""

    if not isinstance(question, dict):
        raise HTTPException(
            status_code=500,
            detail="The pending question is invalid. Please refresh and try again.",
        )

    if not isinstance(answer, str):
        raise HTTPException(
            status_code=422,
            detail="Please enter an answer in the expected format.",
        )

    answer = answer.strip()

    if not answer:
        raise HTTPException(
            status_code=422,
            detail="Please provide an answer before continuing.",
        )

    question_type = question.get("type")

    if question_type == "text":
        if len(answer) > 5000:
            raise HTTPException(
                status_code=422,
                detail="Your answer must be 5,000 characters or fewer.",
            )
        return answer

    if question_type == "single_choice":
        options = question.get("options")

        if not isinstance(options, list) or not options:
            logger.error("Pending single-choice question has invalid options.")
            raise HTTPException(
                status_code=500,
                detail="This question is temporarily unavailable. Please try again.",
            )

        valid_values = {
            option["value"]
            for option in options
            if isinstance(option, dict)
            and isinstance(option.get("value"), str)
            and option["value"].strip()
        }

        if not valid_values:
            logger.error("Pending question contains no valid choice values.")
            raise HTTPException(
                status_code=500,
                detail="This question is temporarily unavailable. Please try again.",
            )

        if answer not in valid_values:
            raise HTTPException(
                status_code=422,
                detail="Please select one of the available options.",
            )

        return answer

    if question_type == "number":
        try:
            number = float(answer)
        except (ValueError, OverflowError):
            raise HTTPException(
                status_code=422,
                detail="Please enter a valid number, such as 16 or 3.5.",
            )

        if not math.isfinite(number):
            raise HTTPException(
                status_code=422,
                detail="Please enter a finite number.",
            )

        # Respect optional limits if a future question defines them.
        minimum = question.get("min")
        maximum = question.get("max")

        if minimum is not None and number < minimum:
            raise HTTPException(
                status_code=422,
                detail=f"Please enter a number of at least {minimum}.",
            )

        if maximum is not None and number > maximum:
            raise HTTPException(
                status_code=422,
                detail=f"Please enter a number no greater than {maximum}.",
            )

        return answer

    logger.error("Unsupported pending question type: %r", question_type)
    raise HTTPException(
        status_code=500,
        detail="This question has an unsupported format. Please try again.",
    )


    if question_type == "number":
        try:
            number = float(answer)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="Enter a valid number.",
            )

        if not math.isfinite(number):
            raise HTTPException(
                status_code=422,
                detail="The number must be finite.",
            )

        return answer

    raise HTTPException(
        status_code=500,
        detail="Unsupported pending question type.",
    )


def validate_generated_result(result, answered_ids):
    """Validate AI output again before saving or returning it."""

    if not isinstance(result, dict):
        raise ValueError("AI output must be a JSON object.")

    status = result.get("status")

    if status not in {"ask", "complete"}:
        raise ValueError("Invalid AI status.")

    reason = result.get("reason", "")

    if not isinstance(reason, str) or len(reason) > 2000:
        raise ValueError("Invalid AI reason.")

    if status == "complete":
        return {
            "status": "complete",
            "question": None,
            "reason": reason,
            "profile_updates": [],
            "unknowns": result.get("unknowns", []),
        }

    question = result.get("question")

    if not isinstance(question, dict):
        raise ValueError("AI did not return a valid question.")

    question_id = question.get("id")
    question_text = question.get("text")
    question_type = question.get("type")

    if (
        not isinstance(question_id, str)
        or not question_id.strip()
        or len(question_id) > 100
    ):
        raise ValueError("Invalid question ID.")

    if question_id in answered_ids:
        raise ValueError("AI generated a question that was already answered.")

    if (
        not isinstance(question_text, str)
        or not question_text.strip()
        or len(question_text) > 2000
    ):
        raise ValueError("Invalid question text.")

    if question_type not in {"text", "single_choice", "number"}:
        raise ValueError("Unsupported question type.")

    clean_question = {
        "id": question_id,
        "text": question_text.strip(),
        "type": question_type,
    }

    if question_type == "single_choice":
        options = question.get("options")

        if not isinstance(options, list) or not 2 <= len(options) <= 12:
            raise ValueError("Choice questions need 2–12 options.")

        clean_options = []
        seen_values = set()

        for option in options:
            if not isinstance(option, dict):
                raise ValueError("Invalid choice option.")

            label = option.get("label")
            value = option.get("value")

            if (
                not isinstance(label, str)
                or not label.strip()
                or len(label) > 200
                or not isinstance(value, str)
                or not value.strip()
                or len(value) > 200
            ):
                raise ValueError("Invalid option label or value.")

            if value in seen_values:
                raise ValueError("Duplicate option values.")

            seen_values.add(value)
            clean_options.append({
                "label": label.strip(),
                "value": value,
            })

        clean_question["options"] = clean_options

    unknowns = result.get("unknowns", [])

    if not isinstance(unknowns, list) or len(unknowns) > 50:
        raise ValueError("Invalid unknowns list.")

    return {
        "status": "ask",
        "question": clean_question,
        "reason": reason,
        "profile_updates": [],
        "unknowns": unknowns,
    }


# --------------------------------------------------
# 5. START ONBOARDING
# --------------------------------------------------

@router.post("/start")
def start_onboarding(user=Depends(get_current_user)):
    ensure_onboarding_schema()

    session_id = str(uuid.uuid4())
    user_id = user["id"]

    initial_question = json.dumps(FIRST_QUESTION)

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
                user_id,
                "in_progress",
                datetime.now(timezone.utc).isoformat(),
                initial_question,
            ),
        )

    return {
        "session_id": session_id,
        **FIRST_QUESTION,
    }


# --------------------------------------------------
# 6. SUBMIT AN ANSWER
# --------------------------------------------------

@router.post("/answer")
def submit_answer(
    data: AnswerInput,
    user=Depends(get_current_user),
):
    ensure_onboarding_schema()

    session_id = str(data.session_id)
    user_id = user["id"]

    with get_connection() as db:
        # Serializes answer submissions for this SQLite database.
        db.execute("BEGIN IMMEDIATE")

        session = get_owned_session(db, session_id, user_id)

        if session["status"] != "in_progress":
            raise HTTPException(
                status_code=409,
                detail=(
                    "This session is not accepting answers right now. "
                    "Call GET /onboarding/next to check its state."
                ),
            )

        pending = parse_json(
            session["current_question_json"],
            None,
        )

        if not isinstance(pending, dict):
            raise HTTPException(
                status_code=409,
                detail="There is no pending question for this session.",
            )

        question = pending.get("question")

        if not isinstance(question, dict):
            raise HTTPException(
                status_code=500,
                detail="The pending question is invalid.",
            )

        if data.question_id != question.get("id"):
            raise HTTPException(
                status_code=409,
                detail="This is not the current question.",
            )

        clean_answer = validate_answer(question, data.answer)

        try:
            db.execute(
                """
                INSERT INTO onboarding_answers (
                    session_id,
                    question_id,
                    answer,
                    created_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    session_id,
                    data.question_id,
                    clean_answer,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(
                status_code=409,
                detail="An answer for this question already exists.",
            )

        # Save the role to the base profile, but keep all answers
        # in the answers table as the authoritative record.
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
                    json.dumps(profile, ensure_ascii=False),
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

    # The answer is committed before the external AI call.
    result = generate_and_store_next(session_id, user_id)

    return {
        "session_id": session_id,
        "answer_saved": True,
        **result,
    }


# --------------------------------------------------
# 7. GENERATE AND STORE THE NEXT QUESTION
# --------------------------------------------------

def generate_and_store_next(session_id, user_id):
    now = datetime.now(timezone.utc)

    # Atomically claim this session so two requests don't normally
    # generate and save separate questions at the same time.
    with get_connection() as db:
        db.execute("BEGIN IMMEDIATE")

        session = get_owned_session(db, session_id, user_id)

        if session["status"] == "completed":
            return get_completed_response(db, session_id, user_id)

        if session["status"] == "in_progress":
            current = parse_json(
                session["current_question_json"],
                None,
            )

            if isinstance(current, dict):
                return current

            raise HTTPException(
                status_code=409,
                detail="No current question is available.",
            )

        if session["status"] == "generating":
            started_at = session["generation_started_at"]

            try:
                started = datetime.fromisoformat(started_at)
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                started = now - timedelta(
                    seconds=GENERATION_TIMEOUT_SECONDS + 1
                )

            if (
                now - started
            ).total_seconds() <= GENERATION_TIMEOUT_SECONDS:
                raise HTTPException(
                    status_code=409,
                    detail="A question is already being generated. Try again shortly.",
                )

            # Recover a generation lock left behind by a crashed request.
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
                detail="This session cannot generate a question in its current state.",
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
            (now.isoformat(), session_id, user_id),
        )

        if claimed.rowcount != 1:
            raise HTTPException(
                status_code=409,
                detail="Could not claim this session for question generation.",
            )

        profile = get_profile(db, user_id)
        answers = get_session_answers(db, session_id)

    # The slow external API call happens outside the DB transaction.
    try:
        result = generate_next_question(profile, answers)

        answered_ids = {
            item["question_id"]
            for item in answers
        }

        result = validate_generated_result(result, answered_ids)

    except Exception as exc:
        # Allow a later /next request to retry after a model/API failure.
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
            "Adaptive question generation failed for session %s (%s).",
            session_id,
            type(exc).__name__,
        )

        raise HTTPException(
            status_code=502,
            detail=(
                "The adaptive engine could not generate the next question. "
                "Your answer was saved; call GET /onboarding/next to retry."
            ),
        )

    # Store the generated question or mark the session complete.
    with get_connection() as db:
        db.execute("BEGIN IMMEDIATE")

        session = get_owned_session(db, session_id, user_id)

        # Another request may have recovered a stale generation lock.
        # Do not overwrite a newer state with an old result.
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
                    db, session_id, user_id
                )

            raise HTTPException(
                status_code=409,
                detail="The session state changed during generation. Call /next.",
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

            return get_completed_response(db, session_id, user_id)

        db.execute(
            """
            UPDATE onboarding_sessions
            SET status = 'in_progress',
                current_question_json = ?,
                generation_started_at = NULL
            WHERE id = ? AND user_id = ?
            """,
            (
                json.dumps(result, ensure_ascii=False),
                session_id,
                user_id,
            ),
        )

    return result


# --------------------------------------------------
# 8. GET CURRENT QUESTION OR RETRY GENERATION
# --------------------------------------------------

@router.get("/next")
def get_next_question(
    session_id: uuid.UUID = Query(...),
    user=Depends(get_current_user),
):
    ensure_onboarding_schema()

    session_id = str(session_id)
    user_id = user["id"]

    with get_connection() as db:
        session = get_owned_session(db, session_id, user_id)

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
                db, session_id, user_id
            )

        if session["status"] == "generating":
            started_at = session["generation_started_at"]

            try:
                started = datetime.fromisoformat(started_at)
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                started = datetime.min.replace(tzinfo=timezone.utc)

            if (
                datetime.now(timezone.utc) - started
            ).total_seconds() <= GENERATION_TIMEOUT_SECONDS:
                raise HTTPException(
                    status_code=409,
                    detail="Question generation is still in progress. Try again shortly.",
                )

    # This also recovers a stale generation lock and retries the model.
    return generate_and_store_next(session_id, user_id)


# --------------------------------------------------
# 9. VIEW PROFILE AND ANSWERS
# --------------------------------------------------

@router.get("/profile")
def get_onboarding_profile(user=Depends(get_current_user)):
    ensure_onboarding_schema()

    user_id = user["id"]

    with get_connection() as db:
        profile = get_profile(db, user_id)

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
