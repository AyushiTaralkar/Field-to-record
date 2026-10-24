
from datetime import datetime

from app.database import init_db, get_record, save_record
from app.audit import init_audit_table, log_event


def finalize_record(record_id: str) -> dict:
    """Finalize a reviewed record and log the action."""

    record = get_record(record_id)

    if record is None:
        raise ValueError("Record not found.")

    if record.get("status") != "reviewed":
        raise ValueError(
            "Only reviewed records can be finalized. "
            f"Current status: {record.get('status')}"
        )

    record["status"] = "finalized"
    record["finalized_at"] = (
        datetime.now()
        .astimezone()
        .isoformat(timespec="seconds")
    )

    save_record(record)

    log_event(
        record_id,
        "record_finalized",
        {
            "status": "finalized",
            "finalized_at": record["finalized_at"],
        },
    )

    return record


if __name__ == "__main__":
    init_db()
    init_audit_table()

    record_id = input("Enter the reviewed record ID: ").strip()

    try:
        record = finalize_record(record_id)
        print("\nRecord finalized successfully.")
        print("Record ID:", record["record_id"])
        print("Status:", record["status"])
        print("Finalized at:", record["finalized_at"])
    except ValueError as error:
        print("\nFinalization refused:", error)
