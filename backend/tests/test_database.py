import sqlite3


def test_database_uses_configured_path_from_environment(tmp_path, monkeypatch):
    import importlib

    import database

    original_path = database.DB_PATH
    configured_path = tmp_path / "persistent" / "stratify.db"
    monkeypatch.setattr(database, "DB_PATH", original_path)
    monkeypatch.setenv("DB_PATH", str(configured_path))

    reloaded_database = importlib.reload(database)
    assert reloaded_database.DB_PATH == configured_path

    reloaded_database.init_db()
    assert configured_path.is_file()


def test_legacy_users_receive_unique_stratify_usernames(tmp_path, monkeypatch):
    database_path = tmp_path / "legacy.db"
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            name TEXT NOT NULL DEFAULT '',
            password_hash TEXT NOT NULL,
            profile_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        )
        """
    )
    connection.executemany(
        """
        INSERT INTO users (email, name, password_hash, profile_json, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            ("same@example.com", "First User", "hash-1", '{"kept": 1}', "now"),
            ("same@elsewhere.com", "Second User", "hash-2", "{}", "now"),
            ("bad!name@example.com", "Third User", "hash-3", "{}", "now"),
        ],
    )
    connection.commit()
    connection.close()

    import database

    monkeypatch.setattr(database, "DB_PATH", database_path)
    database.init_db()

    with database.get_connection() as db:
        users = db.execute(
            "SELECT id, username, name, password_hash, profile_json FROM users "
            "ORDER BY id"
        ).fetchall()

    assert [user["username"] for user in users] == [
        "same",
        "member2",
        "member3",
    ]
    assert users[0]["name"] == "First User"
    assert users[0]["password_hash"] == "hash-1"
    assert users[0]["profile_json"] == '{"kept": 1}'


def test_legacy_chat_messages_receive_nullable_analysis_column(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "legacy_chat.db"
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        CREATE TABLE chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        INSERT INTO chat_messages (conversation_id, role, content, created_at)
        VALUES ('legacy-conversation', 'assistant', 'An older reply.', 'now')
        """
    )
    connection.commit()
    connection.close()

    import database

    monkeypatch.setattr(database, "DB_PATH", database_path)
    database.init_db()

    with database.get_connection() as db:
        message = db.execute(
            """
            SELECT content, analysis_json
            FROM chat_messages
            WHERE conversation_id = 'legacy-conversation'
            """
        ).fetchone()

    assert message["content"] == "An older reply."
    assert message["analysis_json"] is None


def test_legacy_onboarding_answers_receive_question_text_column(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "legacy_onboarding.db"
    connection = sqlite3.connect(database_path)
    connection.executescript(
        """
        CREATE TABLE onboarding_sessions (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE onboarding_answers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            question_id TEXT NOT NULL,
            answer TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        INSERT INTO onboarding_sessions (
            id, user_id, status, created_at
        ) VALUES ('legacy-session', 1, 'completed', 'now');
        INSERT INTO onboarding_answers (
            session_id, question_id, answer, created_at
        ) VALUES ('legacy-session', 'role', 'student', 'now');
        """
    )
    connection.commit()
    connection.close()

    import database

    monkeypatch.setattr(database, "DB_PATH", database_path)
    database.init_db()

    with database.get_connection() as db:
        answer = db.execute(
            """
            SELECT question_id, question_text, answer
            FROM onboarding_answers
            WHERE session_id = 'legacy-session'
            """
        ).fetchone()

    assert answer["question_id"] == "role"
    assert answer["question_text"] == ""
    assert answer["answer"] == "student"
