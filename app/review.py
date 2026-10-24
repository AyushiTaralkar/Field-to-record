
from copy import deepcopy

from app.structure import structure_record
from app.database import init_db, save_record
from app.audit import init_audit_table, log_event


def review_record(draft: dict) -> dict:
    """Review a draft, save it, and log workflow events."""

    if draft.get("status") != "draft":
        raise ValueError("Only draft records can be reviewed.")

    record = deepcopy(draft)

    print("\n=== FIELD-TO-RECORD: HUMAN REVIEW ===")
    print("Record ID:", record["record_id"])
    print("Original note:", record["original_note"])

    print("\nExtracted medications:")
    for index, medication in enumerate(record["medications"], start=1):
        print(f"\n{index}. {medication['medication_name']}")
        for attribute, values in medication["attributes"].items():
            texts = ", ".join(item["text"] for item in values)
            print(f"   {attribute}: {texts}")

    print("\nReview each medication.")
    print("Press Enter to keep a value unchanged.")

    for index, medication in enumerate(record["medications"], start=1):
        print(f"\nMedication {index}: {medication['medication_name']}")

        corrected_name = input(
            f"Correct medication name [{medication['medication_name']}] "
            "(Enter to keep): "
        ).strip()

        if corrected_name and corrected_name.upper() != "REVIEWED":
            original_name = medication["medication_name"]
            medication.setdefault("corrections", {})["medication_name"] = {
                "original": original_name,
                "corrected": corrected_name,
            }
            medication["medication_name"] = corrected_name

        for attribute, values in medication["attributes"].items():
            current_value = ", ".join(item["text"] for item in values)
            corrected_value = input(
                f"{attribute} [{current_value}]: "
            ).strip()

            if corrected_value and corrected_value.upper() != "REVIEWED":
                medication.setdefault("corrections", {})[attribute] = {
                    "original": [item["text"] for item in values],
                    "corrected": corrected_value,
                }

    confirmation = input(
        "\nType REVIEWED to confirm the review: "
    ).strip()

    if confirmation.upper() != "REVIEWED":
        save_record(record)
        print("Review not confirmed. Record remains a draft.")
        return record

    record["status"] = "reviewed"
    record["reviewed_at"] = (
        __import__("datetime").datetime.now()
        .astimezone()
        .isoformat(timespec="seconds")
    )

    # Persist the reviewed record.
    save_record(record)

    # Record the review action in the audit log.
    log_event(
        record["record_id"],
        "record_reviewed",
        {
            "status": "reviewed",
            "corrections_made": bool(
                any("corrections" in med for med in record["medications"])
            ),
        },
    )

    print("\nRecord reviewed successfully.")
    print("Status:", record["status"])
    print("Reviewed at:", record["reviewed_at"])

    return record


if __name__ == "__main__":
    import json

    init_db()
    init_audit_table()

    note = input("\nEnter a clinical note: ").strip()
    if not note:
        raise SystemExit("Clinical note cannot be empty.")

    draft = structure_record(note)

    # Save and audit creation before review begins.
    save_record(draft)
    log_event(
        draft["record_id"],
        "record_created",
        {"status": "draft"},
    )

    reviewed_record = review_record(draft)

    print("\n=== REVIEW RESULT ===")
    print(json.dumps(reviewed_record, indent=2, ensure_ascii=False))
