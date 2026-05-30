"""
Authentication and session storage for the Emergency Response Agent.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import threading
import time
from collections import defaultdict, deque
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "auth.db"
SESSION_COOKIE_NAME = "era_session"
SESSION_MAX_AGE_SECONDS = int(os.getenv("AUTH_SESSION_HOURS", "12")) * 60 * 60
SESSION_COOKIE_SECURE = os.getenv("AUTH_COOKIE_SECURE", "0").lower() in {"1", "true", "yes"}
PASSWORD_ITERATIONS = 260_000
LOGIN_WINDOW_SECONDS = 15 * 60
MAX_LOGIN_ATTEMPTS = 5

ROLE_DEFINITIONS = {
    "administrator": {
        "label": "Administrator",
        "summary": "Full mission control access.",
        "permissions": {
            "generate_map": True,
            "edit_terrain": True,
            "dispatch_route": True,
        },
    },
    "dispatcher": {
        "label": "Dispatcher",
        "summary": "Can generate scenarios and launch dispatch runs.",
        "permissions": {
            "generate_map": True,
            "edit_terrain": False,
            "dispatch_route": True,
        },
    },
    "planner": {
        "label": "Planning Analyst",
        "summary": "Can prepare terrain but cannot launch dispatch runs.",
        "permissions": {
            "generate_map": True,
            "edit_terrain": True,
            "dispatch_route": False,
        },
    },
    "observer": {
        "label": "Observer",
        "summary": "Read-only access for live monitoring.",
        "permissions": {
            "generate_map": False,
            "edit_terrain": False,
            "dispatch_route": False,
        },
    },
}

DEFAULT_USERS = (
    {
        "username": "aria.admin",
        "email": "admin@response.local",
        "display_name": "Aria Chen",
        "role": "administrator",
        "password_env": "ERA_ADMIN_PASSWORD",
        "default_password": "AdminDemo123!",
    },
    {
        "username": "miles.dispatch",
        "email": "dispatcher@response.local",
        "display_name": "Miles Carter",
        "role": "dispatcher",
        "password_env": "ERA_DISPATCHER_PASSWORD",
        "default_password": "DispatchDemo123!",
    },
    {
        "username": "leena.planner",
        "email": "planner@response.local",
        "display_name": "Leena Shah",
        "role": "planner",
        "password_env": "ERA_PLANNER_PASSWORD",
        "default_password": "PlannerDemo123!",
    },
    {
        "username": "noah.observe",
        "email": "observer@response.local",
        "display_name": "Noah Brooks",
        "role": "observer",
        "password_env": "ERA_OBSERVER_PASSWORD",
        "default_password": "ObserverDemo123!",
    },
)


class LoginError(Exception):
    def __init__(self, message: str, status_code: int, retry_after: int | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.retry_after = retry_after


_failed_attempts: dict[str, deque[float]] = defaultdict(deque)
_attempts_lock = threading.Lock()


def init_auth_storage() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                role TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                session_hash TEXT NOT NULL UNIQUE,
                ip_address TEXT,
                user_agent TEXT,
                created_at INTEGER NOT NULL,
                last_seen_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_hash ON sessions(session_hash)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at)"
        )
        _prune_expired_sessions(conn)
        user_count = conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"]
        if user_count == 0:
            now_ts = _now_ts()
            for config in DEFAULT_USERS:
                password = os.getenv(config["password_env"]) or config["default_password"]
                conn.execute(
                    """
                    INSERT INTO users (username, email, display_name, role, password_hash, active, created_at)
                    VALUES (?, ?, ?, ?, ?, 1, ?)
                    """,
                    (
                        config["username"],
                        config["email"],
                        config["display_name"],
                        config["role"],
                        _hash_password(password),
                        now_ts,
                    ),
                )
        conn.commit()


def authenticate_user(identifier: str, password: str, ip_address: str, user_agent: str):
    normalized = _normalize_identifier(identifier)
    password = password or ""
    blocked, retry_after = _login_blocked(normalized, ip_address)
    if blocked:
        raise LoginError("Too many sign-in attempts. Try again shortly.", 429, retry_after)

    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id, username, email, display_name, role, password_hash, active
            FROM users
            WHERE lower(username) = ? OR lower(email) = ?
            LIMIT 1
            """,
            (normalized, normalized),
        ).fetchone()

    if row is None or not _verify_password(password, row["password_hash"]):
        _record_failed_attempt(normalized, ip_address)
        raise LoginError("Invalid username/email or password.", 401)

    if not row["active"]:
        raise LoginError("This account is disabled.", 403)

    _clear_failed_attempts(normalized, ip_address)
    session_token = create_session(row["id"], ip_address, user_agent)
    return _public_user(row), session_token


def create_session(user_id: int, ip_address: str, user_agent: str) -> str:
    raw_token = secrets.token_urlsafe(32)
    token_hash = _session_hash(raw_token)
    now_ts = _now_ts()
    expires_at = now_ts + SESSION_MAX_AGE_SECONDS
    with _connect() as conn:
        _prune_expired_sessions(conn)
        conn.execute(
            """
            INSERT INTO sessions (user_id, session_hash, ip_address, user_agent, created_at, last_seen_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, token_hash, ip_address, user_agent[:255], now_ts, now_ts, expires_at),
        )
        conn.commit()
    return raw_token


def get_user_by_session(session_token: str | None):
    if not session_token:
        return None

    token_hash = _session_hash(session_token)
    now_ts = _now_ts()
    with _connect() as conn:
        _prune_expired_sessions(conn)
        row = conn.execute(
            """
            SELECT users.id, users.username, users.email, users.display_name, users.role, users.active
            FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.session_hash = ? AND sessions.expires_at >= ?
            LIMIT 1
            """,
            (token_hash, now_ts),
        ).fetchone()
        if row is None or not row["active"]:
            return None
        conn.execute(
            "UPDATE sessions SET last_seen_at = ? WHERE session_hash = ?",
            (now_ts, token_hash),
        )
        conn.commit()
    return _public_user(row)


def revoke_session(session_token: str | None) -> None:
    if not session_token:
        return
    with _connect() as conn:
        conn.execute(
            "DELETE FROM sessions WHERE session_hash = ?",
            (_session_hash(session_token),),
        )
        conn.commit()


def cookie_settings() -> dict[str, object]:
    return {
        "key": SESSION_COOKIE_NAME,
        "httponly": True,
        "max_age": SESSION_MAX_AGE_SECONDS,
        "path": "/",
        "secure": SESSION_COOKIE_SECURE,
        "samesite": "lax",
    }


def local_seeded_accounts() -> list[dict[str, str]]:
    accounts = []
    for config in DEFAULT_USERS:
        accounts.append(
            {
                "role": config["role"],
                "role_label": ROLE_DEFINITIONS[config["role"]]["label"],
                "username": config["username"],
                "email": config["email"],
                "password": os.getenv(config["password_env"]) or config["default_password"],
            }
        )
    return accounts


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _public_user(row: sqlite3.Row) -> dict[str, object]:
    role = row["role"] if row["role"] in ROLE_DEFINITIONS else "observer"
    role_details = ROLE_DEFINITIONS[role]
    return {
        "id": row["id"],
        "username": row["username"],
        "email": row["email"],
        "display_name": row["display_name"],
        "role": role,
        "role_label": role_details["label"],
        "role_summary": role_details["summary"],
        "permissions": dict(role_details["permissions"]),
    }


def _now_ts() -> int:
    return int(time.time())


def _normalize_identifier(identifier: str) -> str:
    return (identifier or "").strip().lower()


def _hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS
    )
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = stored_hash.split("$", 3)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    candidate = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt_hex),
        int(iterations),
    )
    return hmac.compare_digest(candidate.hex(), digest_hex)


def _session_hash(session_token: str) -> str:
    return hashlib.sha256(session_token.encode("utf-8")).hexdigest()


def _prune_expired_sessions(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM sessions WHERE expires_at < ?", (_now_ts(),))


def _attempt_key(identifier: str, ip_address: str) -> str:
    return f"{ip_address}:{identifier or '<blank>'}"


def _login_blocked(identifier: str, ip_address: str) -> tuple[bool, int | None]:
    now_ts = time.time()
    key = _attempt_key(identifier, ip_address)
    with _attempts_lock:
        attempts = _failed_attempts[key]
        while attempts and now_ts - attempts[0] > LOGIN_WINDOW_SECONDS:
            attempts.popleft()
        if len(attempts) < MAX_LOGIN_ATTEMPTS:
            return False, None
        retry_after = max(1, int(LOGIN_WINDOW_SECONDS - (now_ts - attempts[0])))
        return True, retry_after


def _record_failed_attempt(identifier: str, ip_address: str) -> None:
    key = _attempt_key(identifier, ip_address)
    now_ts = time.time()
    with _attempts_lock:
        attempts = _failed_attempts[key]
        while attempts and now_ts - attempts[0] > LOGIN_WINDOW_SECONDS:
            attempts.popleft()
        attempts.append(now_ts)


def _clear_failed_attempts(identifier: str, ip_address: str) -> None:
    key = _attempt_key(identifier, ip_address)
    with _attempts_lock:
        _failed_attempts.pop(key, None)
