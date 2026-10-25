"""Stratify AI authentication (FastAPI + SQLite + bcrypt).
 
Setup:
    pip install bcrypt
    Save as auth.py. Make sure init_db() from database.py (the Postgres version) runs on startup.
 
Design:
  * bcrypt (cost 12) with a SHA-256 prehash, so long passwords never hit
    bcrypt's 72-byte limit.
  * Old PBKDF2 hashes still verify and are upgraded to bcrypt on login.
  * Opaque random session tokens; only their SHA-256 hash is stored.
  * Generic login errors, timing-equalised, with a small in-memory throttle.
"""
 
import base64
import hashlib
import hmac
import re
import secrets
import psycopg
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
 
import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator
 
from database import get_connection
 
 
router = APIRouter(prefix="/auth", tags=["Authentication"])
bearer = HTTPBearer(auto_error=False)
 
USERNAME_DOMAIN = "@stratifyai"
USERNAME_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{1,22}[a-z0-9])$")
 
BCRYPT_ROUNDS = 12
SESSION_TOKEN_BYTES = 32
SESSION_DURATION = timedelta(days=7)
 
# Legacy PBKDF2 settings (only used to verify old accounts)
LEGACY_ITERATIONS = 600_000
LEGACY_SALT_BYTES = 16
 
# Login throttle: max failed attempts per (ip, username) per window
MAX_FAILS = 5
FAIL_WINDOW_SECONDS = 300
 
 
# ------------------------------------------------------------- validation
 
def clean_username(value: str) -> str:
    """Lowercase, trim, strip a leading '@' and a trailing '@stratifyai'."""
    cleaned = value.strip().lower()
    if cleaned.startswith("@"):
        cleaned = cleaned[1:]
    if cleaned.endswith(USERNAME_DOMAIN):
        cleaned = cleaned[: -len(USERNAME_DOMAIN)]
    return cleaned
 
 
class SignupInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=8, max_length=128)
 
    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Name cannot contain only spaces.")
        return normalized
 
    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        normalized = clean_username(value)
        if not USERNAME_PATTERN.fullmatch(normalized) or ".." in normalized:
            raise ValueError(
                "Use 3-24 letters, numbers, dots, underscores or hyphens; "
                "start and end with a letter or number."
            )
        return normalized
 
    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Password cannot contain only spaces.")
        return value
 
 
class LoginInput(BaseModel):
    """Lenient on purpose: bad input becomes a generic 401, not a 422 that
    reveals the signup rules."""
 
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)
 
    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return clean_username(value)
 
 
# --------------------------------------------------------------- passwords
 
def _prehash(password: str) -> bytes:
    """SHA-256 then base64 -> always 44 bytes, no NULs, under bcrypt's limit."""
    return base64.b64encode(hashlib.sha256(password.encode("utf-8")).digest())
 
 
def hash_password(password: str) -> str:
    return bcrypt.hashpw(
        _prehash(password), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
    ).decode("ascii")
 
 
def _verify_legacy(password: str, stored: str) -> bool:
    """Verify an old 'salt_hex$digest_hex' PBKDF2-SHA256 hash."""
    try:
        salt_hex, digest_hex = stored.split("$", 1)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
        if len(salt) != LEGACY_SALT_BYTES or len(expected) != 32:
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, LEGACY_ITERATIONS
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError, AttributeError):
        return False
 
 
def verify_password(password: str, stored: str) -> tuple[bool, bool]:
    """Return (is_valid, needs_rehash)."""
    if not stored:
        return False, False
    if stored.startswith("$2"):
        try:
            ok = bcrypt.checkpw(_prehash(password), stored.encode("ascii"))
        except (ValueError, TypeError):
            ok = False
        return ok, False
    ok = _verify_legacy(password, stored)
    return ok, ok  # a valid legacy hash should be upgraded to bcrypt
 
 
# Burned when a username doesn't exist so timing doesn't reveal it.
DUMMY_HASH = hash_password("stratify-timing-equalizer")
 
 
# ---------------------------------------------------------------- throttle
 
_fails: dict[str, deque] = defaultdict(deque)
_fails_lock = threading.Lock()
 
 
def _throttle_key(request: Request, username: str) -> str:
    ip = request.client.host if request.client else "unknown"
    return f"{ip}|{username}"
 
 
def _check_throttle(key: str) -> None:
    now = time.monotonic()
    with _fails_lock:
        attempts = _fails[key]
        while attempts and now - attempts[0] > FAIL_WINDOW_SECONDS:
            attempts.popleft()
        if not attempts:
            _fails.pop(key, None)
            return
        if len(attempts) >= MAX_FAILS:
            raise HTTPException(
                status_code=429,
                detail="Too many attempts. Please wait a few minutes.",
                headers={"Retry-After": str(FAIL_WINDOW_SECONDS)},
            )
 
 
def _record_failure(key: str) -> None:
    with _fails_lock:
        _fails[key].append(time.monotonic())
 
 
def _clear_failures(key: str) -> None:
    with _fails_lock:
        _fails.pop(key, None)
 
 
# ---------------------------------------------------------------- sessions
 
def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
 
 
def create_login_session(db, user_id: int):
    token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
    expires = (datetime.now(timezone.utc) + SESSION_DURATION).isoformat()
    db.execute(
        "INSERT INTO sessions (token_hash, user_id, expires_at) "
        "VALUES (?, ?, ?)",
        (_hash_token(token), user_id, expires),
    )
    return token, expires
 
 
def _unauthorized(detail: str):
    return HTTPException(
        status_code=401,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )
 
 
def _public_user(user):
    return {
        "id": user["id"],
        "username": user["username"],
        "handle": f"{user['username']}{USERNAME_DOMAIN}",
        "name": user["name"],
    }
 
 
def _auth_response(user, token, expires):
    return {
        "user": _public_user(user),
        "access_token": token,
        "token_type": "bearer",
        "expires_at": expires,
    }
 
 
# ------------------------------------------------------------------ routes
 
@router.post("/signup", status_code=201)
def signup(data: SignupInput):
    username = data.username
    handle = f"{username}{USERNAME_DOMAIN}"
    now = datetime.now(timezone.utc).isoformat()
    password_hash = hash_password(data.password)
    taken_detail = "That Stratify username is already taken."
 
    try:
        with get_connection() as db:
            exists = db.execute(
                "SELECT 1 FROM users "
                "WHERE lower(username) = ? OR lower(email) = ?",
                (username, handle),
            ).fetchone()
            if exists:
                raise HTTPException(status_code=409, detail=taken_detail)
 
            cursor = db.execute(
                "INSERT INTO users (email, username, name, password_hash, "
                "created_at) VALUES (?, ?, ?, ?, ?) RETURNING id",
                (handle, username, data.name, password_hash, now),
            )
            user_id = cursor.fetchone()["id"]
            token, expires = create_login_session(db, user_id)
            user = db.execute(
                "SELECT id, username, name FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
    except psycopg.IntegrityError as exc:
        # Race condition or schema problem: only claim "taken" if it is.
        with get_connection() as db:
            taken = db.execute(
                "SELECT 1 FROM users WHERE lower(username) = ?",
                (username,),
            ).fetchone()
        if taken:
            raise HTTPException(status_code=409, detail=taken_detail) from exc
        raise HTTPException(
            status_code=500,
            detail="Could not create the account. Please try again.",
        ) from exc
 
    return _auth_response(user, token, expires)
 
 
@router.post("/login")
def login(data: LoginInput, request: Request):
    key = _throttle_key(request, data.username)
    _check_throttle(key)
 
    handle = f"{data.username}{USERNAME_DOMAIN}"
    result = None
 
    with get_connection() as db:
        user = db.execute(
            "SELECT id, username, name, password_hash FROM users "
            "WHERE lower(username) = ? OR lower(email) = ?",
            (data.username, handle),
        ).fetchone()
 
        stored = user["password_hash"] if user else DUMMY_HASH
        ok, needs_rehash = verify_password(data.password, stored)
 
        if user is not None and ok:
            if needs_rehash:
                db.execute(
                    "UPDATE users SET password_hash = ? WHERE id = ?",
                    (hash_password(data.password), user["id"]),
                )
            db.execute(
                "DELETE FROM sessions WHERE expires_at < ?",
                (datetime.now(timezone.utc).isoformat(),),
            )
            token, expires = create_login_session(db, user["id"])
            result = _auth_response(user, token, expires)
 
    # Raise outside the with-block so nothing gets rolled back unexpectedly.
    if result is None:
        _record_failure(key)
        raise _unauthorized("Invalid Stratify username or password.")
 
    _clear_failures(key)
    return result
 
 
@router.post("/logout", status_code=204)
def logout(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
):
    """Revoke the current session server-side. Safe to call repeatedly."""
    if credentials and credentials.credentials:
        with get_connection() as db:
            db.execute(
                "DELETE FROM sessions WHERE token_hash = ?",
                (_hash_token(credentials.credentials),),
            )
 
 
def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
):
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized("Login required.")
 
    token = credentials.credentials
    if not token or len(token) > 512:
        raise _unauthorized("Invalid login session.")
 
    token_hash = _hash_token(token)
    problem = None
    row = None
 
    with get_connection() as db:
        row = db.execute(
            """
            SELECT u.id, u.email, u.username, u.name, u.profile_json,
                   s.expires_at
            FROM sessions AS s
            JOIN users AS u ON u.id = s.user_id
            WHERE s.token_hash = ?
            """,
            (token_hash,),
        ).fetchone()
 
        if row is None:
            problem = "Invalid login session."
        else:
            try:
                expires = datetime.fromisoformat(row["expires_at"])
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=timezone.utc)
                if expires <= datetime.now(timezone.utc):
                    problem = "Login session expired."
            except (TypeError, ValueError):
                problem = "Invalid login session."
 
            if problem:
                db.execute(
                    "DELETE FROM sessions WHERE token_hash = ?",
                    (token_hash,),
                )
 
    if problem:
        raise _unauthorized(problem)
 
    return {
        "id": row["id"],
        "email": row["email"],
        "username": row["username"],
        "name": row["name"],
        "profile_json": row["profile_json"],
    }
 
 
@router.get("/me")
def me(user=Depends(get_current_user)):
    return {
        "id": user["id"],
        "username": user["username"],
        "handle": f"{user['username']}{USERNAME_DOMAIN}",
        "name": user["name"],
    }
 