
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field, field_validator

from database import get_connection


router = APIRouter(prefix="/auth", tags=["Authentication"])
bearer = HTTPBearer(auto_error=False)

PASSWORD_ITERATIONS = 600_000
PASSWORD_SALT_BYTES = 16
SESSION_TOKEN_BYTES = 32
SESSION_DURATION = timedelta(days=7)


class AuthInput(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Password cannot contain only spaces.")
        return value


def hash_password(password: str) -> str:
    """Hash a password using PBKDF2-HMAC-SHA256 with a random salt."""
    salt = secrets.token_bytes(PASSWORD_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_ITERATIONS,
    )
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Verify a password safely, returning False for malformed hashes."""
    try:
        salt_hex, digest_hex = stored.split("$", 1)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)

        if len(salt) != PASSWORD_SALT_BYTES or len(expected) != 32:
            return False

        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            PASSWORD_ITERATIONS,
        )

        return hmac.compare_digest(actual, expected)

    except (ValueError, TypeError, AttributeError):
        return False


def create_login_session(db, user_id: int):
    """Create a random bearer token; store only its SHA-256 hash."""
    token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    expires = (
        datetime.now(timezone.utc) + SESSION_DURATION
    ).isoformat()

    db.execute(
        """
        INSERT INTO sessions (token_hash, user_id, expires_at)
        VALUES (?, ?, ?)
        """,
        (token_hash, user_id, expires),
    )

    return token, expires


def _unauthorized(detail: str):
    return HTTPException(
        status_code=401,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


@router.post("/signup", status_code=201)
def signup(data: AuthInput):
    email = str(data.email)
    now = datetime.now(timezone.utc).isoformat()
    password_hash = hash_password(data.password)

    try:
        with get_connection() as db:
            cursor = db.execute(
                """
                INSERT INTO users (email, password_hash, created_at)
                VALUES (?, ?, ?)
                """,
                (email, password_hash, now),
            )

            user_id = cursor.lastrowid
            token, expires = create_login_session(db, user_id)

    except Exception as exc:
        # Avoid exposing internal database details to API clients.
        # SQLite's unique constraint is the final duplicate-email guard.
        import sqlite3

        if isinstance(exc, sqlite3.IntegrityError):
            raise HTTPException(
                status_code=409,
                detail="An account with this email already exists.",
            ) from exc
        raise

    return {
        "user": {"id": user_id, "email": email},
        "access_token": token,
        "token_type": "bearer",
        "expires_at": expires,
    }


@router.post("/login")
def login(data: AuthInput):
    email = str(data.email)

    with get_connection() as db:
        user = db.execute(
            """
            SELECT id, email, password_hash
            FROM users
            WHERE email = ?
            """,
            (email,),
        ).fetchone()

        if user is None or not verify_password(
            data.password,
            user["password_hash"],
        ):
            raise _unauthorized("Invalid email or password.")

        token, expires = create_login_session(db, user["id"])

    return {
        "user": {"id": user["id"], "email": user["email"]},
        "access_token": token,
        "token_type": "bearer",
        "expires_at": expires,
    }


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
):
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized("Login required.")

    token = credentials.credentials

    if not token or len(token) > 512:
        raise _unauthorized("Invalid login session.")

    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()

    with get_connection() as db:
        row = db.execute(
            """
            SELECT u.id, u.email, u.profile_json, s.expires_at
            FROM sessions AS s
            JOIN users AS u ON u.id = s.user_id
            WHERE s.token_hash = ?
            """,
            (token_hash,),
        ).fetchone()

        if row is None:
            raise _unauthorized("Invalid login session.")

        try:
            expires = datetime.fromisoformat(row["expires_at"])
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            db.execute(
                "DELETE FROM sessions WHERE token_hash = ?",
                (token_hash,),
            )
            raise _unauthorized("Invalid login session.")

        if expires <= datetime.now(timezone.utc):
            db.execute(
                "DELETE FROM sessions WHERE token_hash = ?",
                (token_hash,),
            )
            raise _unauthorized("Login session expired.")

        return {
            "id": row["id"],
            "email": row["email"],
            "profile_json": row["profile_json"],
        }


@router.get("/me")
def me(user=Depends(get_current_user)):
    return {"id": user["id"], "email": user["email"]}
