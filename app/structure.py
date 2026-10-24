
from datetime import datetime
from uuid import uuid4
import re

from app.ner import extract_entities


STRENGTH_PATTERN = re.compile(
    r"\d+(?:\.\d+)?\s*"
    r"(?:mg|mcg|μg|ug|g|kg|ml|l|units?|iu|mmol|meq)\b",
    re.IGNORECASE,
)


def current_timestamp() -> str:
    """Return the current local time with timezone information."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def merge_fragmented_strengths(entities: list, text: str) -> list:
    """Merge adjacent STRENGTH fragments only when they form a valid dose."""
    merged = []
    index = 0

    while index < len(entities):
        entity = entities[index]

        if entity["type"] != "STRENGTH":
            merged.append(entity)
            index += 1
            continue

        # Collect consecutive strength fragments separated by at most
        # a dot or whitespace. This handles outputs such as 2, ., 5 mg.
        group = [entity]
        end = entity["end"]
        next_index = index + 1

        while next_index < len(entities):
            candidate = entities[next_index]

            if candidate["type"] != "STRENGTH":
                break

            gap = text[end:candidate["start"]]

            if len(gap) > 1 or any(
                char not in ". \t" for char in gap
            ):
                break

            group.append(candidate)
            end = candidate["end"]
            next_index += 1

        combined_text = text[group[0]["start"]:group[-1]["end"]]

        if (
            len(group) > 1
            and STRENGTH_PATTERN.fullmatch(combined_text.strip())
        ):
            merged.append({
                "text": combined_text,
                "type": "STRENGTH",
                "score": min(item["score"] for item in group),
                "start": group[0]["start"],
                "end": group[-1]["end"],
            })
            index = next_index
        else:
            merged.append(entity)
            index += 1

    return merged


def sentence_boundary_between(
    text: str, previous_end: int, current_start: int
) -> bool:
    """Detect a likely sentence boundary between two extracted entities."""
    gap = text[previous_end:current_start]

    return bool(re.search(r"[.!?]\s+[A-Z]", gap))


def structure_record(text: str) -> dict:
    """Convert a clinical note into a structured draft for human review."""

    if not isinstance(text, str) or not text.strip():
        raise ValueError("Clinical note cannot be empty.")

    entities = extract_entities(text)
    entities.sort(key=lambda entity: entity["start"])
    entities = merge_fragmented_strengths(entities, text)

    medications = []
    unassigned_entities = []
    current_medication = None
    previous_entity_end = None

    for entity in entities:
        entity_type = entity["type"]

        if entity_type == "DRUG_NAME":
            current_medication = {
                "medication_name": entity["text"],
                "attributes": {},
                "source_span": {
                    "start": entity["start"],
                    "end": entity["end"],
                },
                "event_timestamp": None,
                "timestamp_source": "unknown",
            }
            medications.append(current_medication)
            previous_entity_end = entity["end"]
            continue

        # Do not attach an entity from a later sentence to the
        # previous medication automatically.
        if current_medication is not None and previous_entity_end is not None:
            if sentence_boundary_between(
                text, previous_entity_end, entity["start"]
            ):
                unassigned_entities.append(entity)
                continue

        if current_medication is not None:
            current_medication["attributes"].setdefault(
                entity_type, []
            ).append({
                "text": entity["text"],
                "score": entity["score"],
                "start": entity["start"],
                "end": entity["end"],
            })
            previous_entity_end = entity["end"]
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
    import json

    sample_note = (
        "Responder reports that at 10:35 AM, the patient was given "
        "Aspirin 300 mg orally. Oxygen was administered by face mask. "
        "The responder also reports that the patient received "
        "Salbutamol 2.5 mg by nebulizer."
    )

    draft = structure_record(sample_note)
    print(json.dumps(draft, indent=2, ensure_ascii=False))
