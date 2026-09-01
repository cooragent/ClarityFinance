"""SQLite-backed application state with append-only snapshots."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = PROJECT_ROOT / "runtime"
DATABASE_FILE = RUNTIME_DIR / "clarity.sqlite3"


def _location(legacy_path: Path) -> tuple[Path, str]:
    path = legacy_path if legacy_path.is_absolute() else PROJECT_ROOT / legacy_path
    path = path.resolve()
    try:
        key = path.relative_to(RUNTIME_DIR).with_suffix("").as_posix()
        return DATABASE_FILE, key
    except ValueError:
        return path.parent / "clarity.sqlite3", path.as_posix()


def connect(database: Path = DATABASE_FILE) -> sqlite3.Connection:
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database, timeout=30)
    connection.execute("PRAGMA journal_mode = WAL")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS state (
            key TEXT PRIMARY KEY,
            version INTEGER NOT NULL,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS state_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT NOT NULL,
            version INTEGER NOT NULL,
            value TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(key, version)
        );
        CREATE TRIGGER IF NOT EXISTS state_snapshots_no_update
        BEFORE UPDATE ON state_snapshots
        BEGIN
            SELECT RAISE(ABORT, 'state snapshots are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS state_snapshots_no_delete
        BEFORE DELETE ON state_snapshots
        BEGIN
            SELECT RAISE(ABORT, 'state snapshots are immutable');
        END;
        """
    )
    return connection


def write_state(legacy_path: Path, value: Any) -> int:
    database, key = _location(legacy_path)
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connect(database) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT version FROM state WHERE key = ?", (key,)).fetchone()
        version = (row[0] if row else 0) + 1
        connection.execute(
            "INSERT INTO state_snapshots(key, version, value, created_at) VALUES (?, ?, ?, ?)",
            (key, version, payload, now),
        )
        connection.execute(
            """INSERT INTO state(key, version, value, updated_at) VALUES (?, ?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET
                 version = excluded.version, value = excluded.value, updated_at = excluded.updated_at""",
            (key, version, payload, now),
        )
    return version


def read_state(legacy_path: Path, default: Any) -> Any:
    database, key = _location(legacy_path)
    with connect(database) as connection:
        row = connection.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
    if row:
        return json.loads(row[0])
    path = legacy_path if legacy_path.is_absolute() else PROJECT_ROOT / legacy_path
    if path.exists():
        value = json.loads(path.read_text(encoding="utf-8"))
        write_state(legacy_path, value)
        return value
    return default


def state_exists(legacy_path: Path) -> bool:
    database, key = _location(legacy_path)
    with connect(database) as connection:
        exists = connection.execute("SELECT 1 FROM state WHERE key = ?", (key,)).fetchone()
    if exists:
        return True
    path = legacy_path if legacy_path.is_absolute() else PROJECT_ROOT / legacy_path
    if path.exists():
        read_state(legacy_path, None)
        return True
    return False


def state_history(legacy_path: Path) -> list[dict[str, Any]]:
    database, key = _location(legacy_path)
    with connect(database) as connection:
        rows = connection.execute(
            "SELECT version, value, created_at FROM state_snapshots WHERE key = ? ORDER BY version",
            (key,),
        ).fetchall()
    return [
        {"version": version, "value": json.loads(value), "created_at": created_at}
        for version, value, created_at in rows
    ]
