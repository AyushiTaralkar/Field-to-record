
from datetime import datetime
from uuid import uuid4

from app.ner import extract_entities


def current_timestamp() -> str:
    """Return the current local time with timezone information."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def structure_record(text: str) -> dict:
    """Convert a clinical note into a structured draft for human review."""

    if not isinstance(text, str) or not text.strip():
        raise ValueError("Clinical note cannot be empty.")

    entities = extract_entities(text)
    entities.sort(key=lambda entity: entity["start"])

    medications = []
    unassigned_entities = []
    current_medication = None

    for entity in entities:
        entity_type = entity["type"]
        entity_text = entity["text"]

        if entity_type == "DRUG_NAME":
            current_medication = {
                "medication_name": entity_text,
                "attributes": {},
                "source_span": {
                    "start": entity["start"],
                    "end": entity["end"],
                },
                "event_timestamp": None,
                "timestamp_source": "unknown",
            }
            medications.append(current_medication)

        elif current_medication is not None:
            current_medication["attributes"].setdefault(
                entity_type, []
            ).append({
                "text": entity_text,
                "score": entity["score"],
                "start": entity["start"],
                "end": entity["end"],
            })

        else:
            unassigned_entities.append(entity)

    return {
        "record_id": str(uuid4()),
        "original_note": text,
        "record_created_at": current_timestamp(),
        "medications": medications,
        "unassigned_entities": unassigned_entities,
        "procedures": [],
        "status": "draft",
        "reviewed_at": None,
        "finalized_at": None,
        "exported_at": None,
    }


if __name__ == "__main__":
    sample_note = (
        "Responder reports Metformin 500 mg tablet by mouth "
        "twice daily. Amoxicillin 500 mg capsule PO for seven days."
    )

    import json

    draft = structure_record(sample_note)
    print(json.dumps(draft, indent=2, ensure_ascii=False))
