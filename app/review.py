
from datetime import datetime
from copy import deepcopy


def current_timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def review_record(draft: dict) -> dict:
    """Allow a human reviewer to inspect and correct a draft."""

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
       medication.setdefault("corrections", {})["medication_name"] = {
        "original": medication["medication_name"],
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
    print("\nConfirm that you reviewed the record.")
    confirmation = input("Type REVIEWED to confirm: ").strip()

    if confirmation.upper() != "REVIEWED":
        print("Review not confirmed. Record remains a draft.")
        return record

    record["status"] = "reviewed"
    record["reviewed_at"] = current_timestamp()

    print("\nRecord reviewed successfully.")
    print("Status:", record["status"])
    print("Reviewed at:", record["reviewed_at"])

    return record


if __name__ == "__main__":
    import json
    from app.structure import structure_record

    note = input("\nEnter a clinical note: ").strip()
    draft = structure_record(note)
    reviewed_record = review_record(draft)

    print("\n=== REVIEW RESULT ===")
    print(json.dumps(reviewed_record, indent=2, ensure_ascii=False))
