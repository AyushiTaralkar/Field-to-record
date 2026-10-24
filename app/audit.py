
import hashlib
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "field_to_record.db"

GENESIS_HASH = "0" * 64


def current_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_audit_table():
    """Create the audit table if it does not exist."""

    with get_connection() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS audit_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                event_timestamp TEXT NOT NULL,
                details_json TEXT NOT NULL,
                previous_hash TEXT NOT NULL,
                event_hash TEXT NOT NULL UNIQUE
            )
        """)

    print("Audit table ready.")


def calculate_hash(
    record_id: str,
    event_type: str,
    event_timestamp: str,
    details_json: str,
    previous_hash: str,
) -> str:
    """Hash the event fields and previous event hash."""

    payload = json.dumps(
        {
            "record_id": record_id,
            "event_type": event_type,
            "event_timestamp": event_timestamp,
            "details_json": details_json,
            "previous_hash": previous_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )

    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def log_event(record_id: str, event_type: str, details: dict | None = None):
    """Append an audit event linked to the previous event."""

    if not record_id.strip():
        raise ValueError("record_id cannot be empty.")

    if not event_type.strip():
        raise ValueError("event_type cannot be empty.")

    details_json = json.dumps(
        details or {},
        sort_keys=True,
        ensure_ascii=False,
    )
    timestamp = current_timestamp()

    with get_connection() as connection:
        # Prevent concurrent writers from selecting the same previous hash.
        connection.execute("BEGIN IMMEDIATE")

        previous = connection.execute("""
            SELECT event_hash
            FROM audit_events
            ORDER BY event_id DESC
            LIMIT 1
        """).fetchone()

        previous_hash = previous["event_hash"] if previous else GENESIS_HASH

        event_hash = calculate_hash(
            record_id,
            event_type,
            timestamp,
            details_json,
            previous_hash,
        )

        connection.execute("""
            INSERT INTO audit_events (
                record_id,
                event_type,
                event_timestamp,
                details_json,
                previous_hash,
                event_hash
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            record_id,
            event_type,
            timestamp,
            details_json,
            previous_hash,
            event_hash,
        ))

    return event_hash


def verify_audit_chain() -> bool:
    """Check event hashes and links from the first event onward."""

    with get_connection() as connection:
        events = connection.execute("""
            SELECT *
            FROM audit_events
            ORDER BY event_id ASC
        """).fetchall()

    previous_hash = GENESIS_HASH

    for event in events:
        if event["previous_hash"] != previous_hash:
            return False

        expected_hash = calculate_hash(
            event["record_id"],
            event["event_type"],
            event["event_timestamp"],
            event["details_json"],
            event["previous_hash"],
        )

        if event["event_hash"] != expected_hash:
            return False

        previous_hash = event["event_hash"]

    return True


def get_events(record_id: str) -> list[dict]:
    """Return the audit history for one record."""

    with get_connection() as connection:
        rows = connection.execute("""
            SELECT
                event_id,
                record_id,
                event_type,
                event_timestamp,
                details_json,
                previous_hash,
                event_hash
            FROM audit_events
            WHERE record_id = ?
            ORDER BY event_id ASC
        """, (record_id,)).fetchall()

    events = []
    for row in rows:
        event = dict(row)
        event["details"] = json.loads(event.pop("details_json"))
        events.append(event)

    return events


if __name__ == "__main__":
    init_audit_table()

    # Synthetic test event.
    test_record_id = "audit-test-record-001"

    log_event(
        test_record_id,
        "record_created",
        {"status": "draft", "source": "synthetic_test"},
    )

    log_event(
        test_record_id,
        "record_reviewed",
        {"status": "reviewed", "source": "synthetic_test"},
    )

    print("Audit chain valid:", verify_audit_chain())
    print(json.dumps(get_events(test_record_id), indent=2))
