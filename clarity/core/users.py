"""Local user accounts and bearer sessions stored in SQLite."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from threading import Lock
from uuid import uuid4

from .state_store import DATABASE_FILE, connect


PASSWORD_ROUNDS = 600_000
SESSION_DAYS = 30
_LOCK = Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _database() -> sqlite3.Connection:
    connection = connect(DATABASE_FILE)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT NOT NULL COLLATE NOCASE UNIQUE,
            display_name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS user_sessions (
            token_hash TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS user_sessions_user_id ON user_sessions(user_id);
        """
    )
    return connection


def _email(value: str) -> str:
    email = value.strip().lower()
    if len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise ValueError("邮箱格式无效")
    return email


def _password_hash(password: str) -> str:
    if not 8 <= len(password) <= 128:
        raise ValueError("密码长度必须为 8 到 128 位")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PASSWORD_ROUNDS)
    return "$".join((str(PASSWORD_ROUNDS), base64.b64encode(salt).decode(), base64.b64encode(digest).decode()))


def _password_matches(password: str, encoded: str) -> bool:
    try:
        rounds, salt, expected = encoded.split("$", 2)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt), int(rounds))
        return hmac.compare_digest(digest, base64.b64decode(expected))
    except (ValueError, TypeError):
        return False


def _public_user(row: sqlite3.Row | tuple) -> dict[str, str]:
    return {"id": row[0], "email": row[1], "display_name": row[2], "created_at": row[3]}


def _new_session(connection: sqlite3.Connection, user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    now = _now()
    connection.execute(
        "INSERT INTO user_sessions(token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (hashlib.sha256(token.encode()).hexdigest(), user_id, now.isoformat(), (now + timedelta(days=SESSION_DAYS)).isoformat()),
    )
    return token


def register_user(email: str, password: str, display_name: str = "") -> dict:
    email = _email(email)
    display_name = display_name.strip() or email.split("@", 1)[0]
    if len(display_name) > 50:
        raise ValueError("用户名不能超过 50 个字符")
    # ponytail: local accounts skip email verification; add it with password recovery for public SaaS.
    with _LOCK, _database() as connection:
        try:
            user_id = uuid4().hex
            created_at = _now().isoformat()
            connection.execute(
                "INSERT INTO users(id, email, display_name, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, email, display_name, _password_hash(password), created_at),
            )
            token = _new_session(connection, user_id)
        except sqlite3.IntegrityError as exc:
            raise ValueError("该邮箱已注册") from exc
    return {"token": token, "user": {"id": user_id, "email": email, "display_name": display_name, "created_at": created_at}}


def login_user(email: str, password: str) -> dict:
    email = _email(email)
    with _LOCK, _database() as connection:
        row = connection.execute(
            "SELECT id, email, display_name, created_at, password_hash FROM users WHERE email = ?", (email,)
        ).fetchone()
        if not row or not _password_matches(password, row[4]):
            raise ValueError("邮箱或密码错误")
        token = _new_session(connection, row[0])
    return {"token": token, "user": _public_user(row)}


def user_for_token(token: str) -> dict | None:
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    now = _now().isoformat()
    with _database() as connection:
        connection.execute("DELETE FROM user_sessions WHERE expires_at <= ?", (now,))
        row = connection.execute(
            """SELECT users.id, users.email, users.display_name, users.created_at
               FROM user_sessions JOIN users ON users.id = user_sessions.user_id
               WHERE user_sessions.token_hash = ? AND user_sessions.expires_at > ?""",
            (token_hash, now),
        ).fetchone()
    return _public_user(row) if row else None


def logout_user(token: str) -> None:
    with _database() as connection:
        connection.execute("DELETE FROM user_sessions WHERE token_hash = ?", (hashlib.sha256(token.encode()).hexdigest(),))
