
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "stratify.db"
BUSY_TIMEOUT_MS = 5_000


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
                password_hash TEXT NOT NULL,
                profile_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
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
                answer TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id)
                    REFERENCES onboarding_sessions(id)
                    ON DELETE CASCADE,
                UNIQUE (session_id, question_id)
            );
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
            SELECT id, email, profile_json
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        ).fetchone()
