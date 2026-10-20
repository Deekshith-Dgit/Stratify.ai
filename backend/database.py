
import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(
    os.getenv(
        "DB_PATH",
        str(Path(__file__).resolve().parent / "stratify.db"),
    )
)
BUSY_TIMEOUT_MS = 5_000
USERNAME_MIGRATION_PATTERN = re.compile(
    r"^[a-z0-9](?:[a-z0-9._-]{1,22}[a-z0-9])$"
)


@contextmanager
def get_connection():
    """Provide a transaction-safe SQLite connection."""
    connection = sqlite3.connect(
        DB_PATH,
        timeout=BUSY_TIMEOUT_MS / 1_000,
    )
    connection.row_factory = sqlite3.Row

    try:
        connection.execute(
            f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}"
        )
        connection.execute("PRAGMA foreign_keys = ON")

        yield connection
        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def _ensure_column(db, table, column, definition):
    """Add a column only when it is missing."""
    existing = {
        row["name"]
        for row in db.execute(
            f"PRAGMA table_info({table})"
        ).fetchall()
    }

    if column not in existing:
        db.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
        )


def init_db():
    """Initialize or safely migrate the existing database."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with get_connection() as db:
        # WAL improves reader/writer concurrency for local SQLite use.
        db.execute("PRAGMA journal_mode = WAL")

        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                name TEXT NOT NULL DEFAULT '',
                password_hash TEXT NOT NULL,
                profile_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS pending_signups (
                email TEXT PRIMARY KEY COLLATE NOCASE,
                name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                expires_at TEXT NOT NULL,
                sent_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS onboarding_sessions (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'in_progress',
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS onboarding_answers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                question_id TEXT NOT NULL,
                question_text TEXT NOT NULL DEFAULT '',
                answer TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id)
                    REFERENCES onboarding_sessions(id)
                    ON DELETE CASCADE,
                UNIQUE (session_id, question_id)
            );

            CREATE TABLE IF NOT EXISTS chat_conversations (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL DEFAULT 'Untitled decision',
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'completed')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (conversation_id)
                    REFERENCES chat_conversations(id)
                    ON DELETE CASCADE
            );
            """
        )

        _ensure_column(db, "users", "name", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(db, "users", "username", "TEXT NOT NULL DEFAULT ''")

        used_usernames = {
            row["username"].lower()
            for row in db.execute(
                "SELECT username FROM users WHERE username != ''"
            )
        }
        legacy_users = db.execute(
            """
            SELECT id, email
            FROM users
            WHERE username = ''
            ORDER BY id
            """
        ).fetchall()
        for user in legacy_users:
            candidate = user["email"].partition("@")[0].lower()
            if (
                not USERNAME_MIGRATION_PATTERN.fullmatch(candidate)
                or ".." in candidate
                or candidate in used_usernames
            ):
                candidate = f"member{user['id']}"

            db.execute(
                "UPDATE users SET username = ? WHERE id = ?",
                (candidate, user["id"]),
            )
            used_usernames.add(candidate)

        db.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_users_username
            ON users(username COLLATE NOCASE)
            """
        )

        # Migrations preserve existing rows and existing table data.
        _ensure_column(
            db,
            "onboarding_sessions",
            "current_question_json",
            "TEXT",
        )
        _ensure_column(
            db,
            "onboarding_sessions",
            "generation_started_at",
            "TEXT",
        )
        _ensure_column(
            db,
            "onboarding_answers",
            "question_text",
            "TEXT NOT NULL DEFAULT ''",
        )
        _ensure_column(
            db,
            "chat_messages",
            "analysis_json",
            "TEXT",
        )

        # Add lookup indexes without changing existing records.
        db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_sessions_user
            ON sessions(user_id)
            """
        )
        db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_onboarding_user_created
            ON onboarding_sessions(user_id, created_at)
            """
        )
        db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_answers_session
            ON onboarding_answers(session_id, id)
            """
        )
        db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_user_updated
            ON chat_conversations(user_id, updated_at DESC)
            """
        )
        db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_messages_conversation
            ON chat_messages(conversation_id, id)
            """
        )

        # Existing duplicate answers must be checked before adding
        # a unique index to a database that might lack the constraint.
        db.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
                ux_onboarding_session_question
            ON onboarding_answers(session_id, question_id)
            """
        )


def get_user_by_id(user_id: int):
    """Return public user/profile fields, never password hashes."""
    with get_connection() as db:
        return db.execute(
            """
            SELECT id, email, username, name, profile_json
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        ).fetchone()
