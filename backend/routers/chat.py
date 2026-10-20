import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from database import get_connection
from routers.auth import get_current_user
from services.chat_engine import generate_reply
from services.profile_engineer import add_personal_memories


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["Chat"])
MAX_HISTORY_MESSAGES = 24


class CreateConversationInput(BaseModel):
    title: str | None = Field(default=None, max_length=80)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class MessageInput(BaseModel):
    content: str = Field(min_length=1, max_length=5000)
    answer_to_message_id: int | None = Field(default=None, gt=0)

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Message cannot contain only spaces.")
        return normalized


class CompleteConversationInput(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=80)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Decision name cannot contain only spaces.")
        return normalized


def _owned_conversation(db, conversation_id: str, user_id: int):
    conversation = db.execute(
        """
        SELECT id, user_id, title, status, created_at, updated_at
        FROM chat_conversations
        WHERE id = ? AND user_id = ?
        """,
        (conversation_id, user_id),
    ).fetchone()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Chat not found.")
    return conversation


def _serialize_message(row) -> dict:
    analysis_json = row["analysis_json"]
    return {
        "id": row["id"],
        "role": row["role"],
        "content": row["content"],
        "analysis": json.loads(analysis_json) if analysis_json else None,
        "created_at": row["created_at"],
    }


@router.get("/conversations")
def list_conversations(user=Depends(get_current_user)):
    with get_connection() as db:
        rows = db.execute(
            """
            SELECT c.id, c.title, c.status, c.created_at, c.updated_at,
                   (SELECT m.content
                    FROM chat_messages AS m
                    WHERE m.conversation_id = c.id
                    ORDER BY m.id DESC LIMIT 1) AS last_message,
                   (SELECT COUNT(*)
                    FROM chat_messages AS m
                    WHERE m.conversation_id = c.id) AS message_count
            FROM chat_conversations AS c
            WHERE c.user_id = ?
            ORDER BY c.updated_at DESC, c.created_at DESC
            """,
            (user["id"],),
        ).fetchall()

    return {
        "conversations": [
            {
                "id": row["id"],
                "title": row["title"],
                "status": row["status"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "last_message": row["last_message"],
                "message_count": row["message_count"],
            }
            for row in rows
        ]
    }


@router.post("/conversations", status_code=201)
def create_conversation(
    data: CreateConversationInput,
    user=Depends(get_current_user),
):
    now = datetime.now(timezone.utc).isoformat()
    conversation_id = str(uuid.uuid4())
    title = data.title or "Untitled decision"

    with get_connection() as db:
        db.execute(
            """
            INSERT INTO chat_conversations (
                id, user_id, title, status, created_at, updated_at
            )
            VALUES (?, ?, ?, 'active', ?, ?)
            """,
            (conversation_id, user["id"], title, now, now),
        )

    return {
        "id": conversation_id,
        "title": title,
        "status": "active",
        "created_at": now,
        "updated_at": now,
        "messages": [],
    }


@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: uuid.UUID,
    user=Depends(get_current_user),
):
    with get_connection() as db:
        conversation = _owned_conversation(
            db,
            str(conversation_id),
            user["id"],
        )
        messages = db.execute(
            """
            SELECT id, role, content, analysis_json, created_at
            FROM chat_messages
            WHERE conversation_id = ?
            ORDER BY id
            """,
            (str(conversation_id),),
        ).fetchall()

    return {
        "id": conversation["id"],
        "title": conversation["title"],
        "status": conversation["status"],
        "created_at": conversation["created_at"],
        "updated_at": conversation["updated_at"],
        "messages": [_serialize_message(row) for row in messages],
    }


@router.post("/conversations/{conversation_id}/messages")
def send_message(
    conversation_id: uuid.UUID,
    data: MessageInput,
    user=Depends(get_current_user),
):
    conversation_id = str(conversation_id)
    follow_up_target = None
    target_follow_up = ""
    message_created_at = datetime.now(timezone.utc).isoformat()
    with get_connection() as db:
        conversation = _owned_conversation(
            db,
            conversation_id,
            user["id"],
        )
        if data.answer_to_message_id is not None:
            follow_up_target = db.execute(
                """
                SELECT id, analysis_json
                FROM chat_messages
                WHERE id = ? AND conversation_id = ? AND role = 'assistant'
                """,
                (data.answer_to_message_id, conversation_id),
            ).fetchone()
            if follow_up_target is None:
                raise HTTPException(
                    status_code=404,
                    detail="The question could not be found in this decision.",
                )
            try:
                target_analysis = json.loads(
                    follow_up_target["analysis_json"] or "{}"
                )
            except json.JSONDecodeError as exc:
                raise HTTPException(
                    status_code=409,
                    detail="This message does not contain an answerable question.",
                ) from exc
            if not target_analysis.get("follow_up"):
                raise HTTPException(
                    status_code=409,
                    detail="This message does not contain an answerable question.",
                )
            if target_analysis.get("follow_up_answer"):
                raise HTTPException(
                    status_code=409,
                    detail="This question has already been answered.",
                )
            target_follow_up = target_analysis["follow_up"]

        history_rows = db.execute(
            """
            SELECT role, content, analysis_json
            FROM chat_messages
            WHERE conversation_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (conversation_id, MAX_HISTORY_MESSAGES),
        ).fetchall()
        profile_row = db.execute(
            "SELECT profile_json FROM users WHERE id = ?",
            (user["id"],),
        ).fetchone()
        onboarding_rows = db.execute(
            """
            SELECT a.question_id, a.question_text, a.answer
            FROM onboarding_answers AS a
            JOIN onboarding_sessions AS s ON s.id = a.session_id
            WHERE s.id = (
                SELECT latest.id
                FROM onboarding_sessions AS latest
                WHERE latest.user_id = ?
                  AND EXISTS (
                      SELECT 1
                      FROM onboarding_answers AS existing_answer
                      WHERE existing_answer.session_id = latest.id
                  )
                ORDER BY latest.created_at DESC, latest.id DESC
                LIMIT 1
            )
            ORDER BY a.id
            """,
            (user["id"],),
        ).fetchall()
        title = conversation["title"]
        if title == "Untitled decision":
            title = " ".join(data.content.split())[:64]
        db.execute(
            """
            INSERT INTO chat_messages (
                conversation_id, role, content, analysis_json, created_at
            )
            VALUES (?, 'user', ?, NULL, ?)
            """,
            (conversation_id, data.content, message_created_at),
        )
        db.execute(
            """
            UPDATE chat_conversations
            SET title = ?, status = 'active', updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (title, message_created_at, conversation_id, user["id"]),
        )

    try:
        profile = json.loads(profile_row["profile_json"] or "{}")
    except (TypeError, json.JSONDecodeError):
        profile = {}
    if not isinstance(profile, dict):
        profile = {}
    if onboarding_rows:
        profile["onboarding_answers"] = [
            {
                "question_id": row["question_id"],
                "question": row["question_text"],
                "answer": row["answer"],
            }
            for row in onboarding_rows
        ]

    history = []
    for row in reversed(history_rows):
        content = row["content"]
        if row["analysis_json"]:
            content = (
                f"{content}\n\nDecision map: "
                f"{row['analysis_json']}"
            )
        history.append({"role": row["role"], "content": content})
    prompt_content = data.content
    if target_follow_up:
        prompt_content = (
            f"Answer to your question, '{target_follow_up}':\n"
            f"{data.content}"
        )
    history.append({"role": "user", "content": prompt_content})

    try:
        analysis = generate_reply(history, profile)
        if not isinstance(analysis, dict):
            raise ValueError("Chat engine returned an invalid decision map.")
        assistant_content = analysis["summary"]
        analysis_json = json.dumps(
            analysis,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    except Exception as exc:
        logger.exception(
            "Chat response generation failed for user %s",
            user["id"],
        )
        raise HTTPException(
            status_code=502,
            detail="Stratify could not respond just now. Please try again.",
        ) from exc

    now = datetime.now(timezone.utc).isoformat()

    with get_connection() as db:
        db.execute("BEGIN IMMEDIATE")
        _owned_conversation(db, conversation_id, user["id"])
        latest_profile_row = db.execute(
            "SELECT profile_json FROM users WHERE id = ?",
            (user["id"],),
        ).fetchone()
        try:
            latest_profile = json.loads(
                latest_profile_row["profile_json"] or "{}"
            )
        except (TypeError, json.JSONDecodeError):
            latest_profile = {}
        if not isinstance(latest_profile, dict):
            latest_profile = {}
        profile_for_storage = {
            key: value
            for key, value in latest_profile.items()
            if key != "onboarding_answers"
        }
        profile_for_storage = add_personal_memories(
            profile_for_storage,
            analysis["personal_memories"],
        )
        if data.answer_to_message_id is not None:
            current_target = db.execute(
                """
                SELECT analysis_json
                FROM chat_messages
                WHERE id = ? AND conversation_id = ? AND role = 'assistant'
                """,
                (data.answer_to_message_id, conversation_id),
            ).fetchone()
            if current_target is None:
                raise HTTPException(
                    status_code=404,
                    detail="The question could not be found in this decision.",
                )
            try:
                current_analysis = json.loads(
                    current_target["analysis_json"] or "{}"
                )
            except json.JSONDecodeError as exc:
                raise HTTPException(
                    status_code=409,
                    detail="This message does not contain an answerable question.",
                ) from exc
            if (
                not current_analysis.get("follow_up")
                or current_analysis.get("follow_up_answer")
            ):
                raise HTTPException(
                    status_code=409,
                    detail="This question has already been answered.",
                )
            current_analysis["follow_up_answer"] = data.content
            db.execute(
                """
                UPDATE chat_messages
                SET analysis_json = ?
                WHERE id = ? AND conversation_id = ? AND role = 'assistant'
                """,
                (
                    json.dumps(
                        current_analysis,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    data.answer_to_message_id,
                    conversation_id,
                ),
            )
        db.execute(
            "UPDATE users SET profile_json = ? WHERE id = ?",
            (
                json.dumps(
                    profile_for_storage,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                user["id"],
            ),
        )
        db.execute(
            """
            INSERT INTO chat_messages (
                conversation_id, role, content, analysis_json, created_at
            )
            VALUES (?, 'assistant', ?, ?, ?)
            """,
            (
                conversation_id,
                assistant_content,
                analysis_json,
                now,
            ),
        )
        db.execute(
            """
            UPDATE chat_conversations
            SET title = ?, status = 'active', updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (title, now, conversation_id, user["id"]),
        )
        messages = db.execute(
            """
            SELECT id, role, content, analysis_json, created_at
            FROM chat_messages
            WHERE conversation_id = ?
            ORDER BY id DESC
            LIMIT 2
            """,
            (conversation_id,),
        ).fetchall()

    return {
        "id": conversation_id,
        "title": title,
        "status": "active",
        "updated_at": now,
        "profile": profile_for_storage,
        "messages": [
            _serialize_message(row)
            for row in reversed(messages)
        ],
    }


@router.patch("/conversations/{conversation_id}/complete")
def complete_conversation(
    conversation_id: uuid.UUID,
    data: CompleteConversationInput | None = None,
    user=Depends(get_current_user),
):
    requested_title = data.title if data else None
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as db:
        conversation = _owned_conversation(
            db,
            str(conversation_id),
            user["id"],
        )
        message_count = db.execute(
            """
            SELECT COUNT(*) AS count
            FROM chat_messages
            WHERE conversation_id = ?
            """,
            (str(conversation_id),),
        ).fetchone()["count"]
        if message_count == 0:
            raise HTTPException(
                status_code=409,
                detail="Send a message before saving this decision.",
            )
        db.execute(
            """
            UPDATE chat_conversations
            SET title = ?, status = 'completed', updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (
                requested_title or conversation["title"],
                now,
                str(conversation_id),
                user["id"],
            ),
        )

    return {
        "id": conversation["id"],
        "title": requested_title or conversation["title"],
        "status": "completed",
        "updated_at": now,
    }


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: uuid.UUID,
    user=Depends(get_current_user),
):
    with get_connection() as db:
        _owned_conversation(db, str(conversation_id), user["id"])
        db.execute(
            """
            DELETE FROM chat_conversations
            WHERE id = ? AND user_id = ?
            """,
            (str(conversation_id), user["id"]),
        )
