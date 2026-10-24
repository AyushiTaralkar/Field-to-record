
import json
import sqlite3
from pathlib import Path
from datetime import datetime


# Store the database inside the project's data folder.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "field_to_record.db"


def current_timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def get_connection():
    """Create a SQLite connection and ensure the data folder exists."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    """Create the records table if it does not exist."""

    with get_connection() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS records (
                record_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                record_created_at TEXT NOT NULL,
                reviewed_at TEXT,
                finalized_at TEXT,
                exported_at TEXT,
                record_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

    print(f"Database ready: {DB_PATH}")


def save_record(record: dict) -> str:
    """Insert a new record or update an existing record."""

    required_fields = [
        "record_id",
        "status",
        "record_created_at",
    ]

    for field in required_fields:
        if not record.get(field):
            raise ValueError(f"Record is missing required field: {field}")

    record_json = json.dumps(record, ensure_ascii=False)
    now = current_timestamp()

    with get_connection() as connection:
        connection.execute("""
            INSERT INTO records (
                record_id,
                status,
                record_created_at,
                reviewed_at,
                finalized_at,
                exported_at,
                record_json,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)

            ON CONFLICT(record_id) DO UPDATE SET
                status = excluded.status,
                reviewed_at = excluded.reviewed_at,
                finalized_at = excluded.finalized_at,
                exported_at = excluded.exported_at,
                record_json = excluded.record_json,
                updated_at = excluded.updated_at
        """, (
            record["record_id"],
            record["status"],
            record["record_created_at"],
            record.get("reviewed_at"),
            record.get("finalized_at"),
            record.get("exported_at"),
            record_json,
            now,
        ))

    return record["record_id"]


def get_record(record_id: str) -> dict | None:
    """Retrieve a complete record by ID."""

    with get_connection() as connection:
        row = connection.execute("""
            SELECT record_json
            FROM records
            WHERE record_id = ?
        """, (record_id,)).fetchone()

    if row is None:
        return None

    return json.loads(row["record_json"])


def list_records() -> list[dict]:
    """List saved records without returning their full clinical notes."""

    with get_connection() as connection:
        rows = connection.execute("""
            SELECT
                record_id,
                status,
                record_created_at,
                reviewed_at,
                updated_at
            FROM records
            ORDER BY record_created_at DESC
        """).fetchall()

    return [dict(row) for row in rows]


if __name__ == "__main__":
    init_db()
