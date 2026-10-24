
import re
import uuid
from datetime import datetime

from app.ner import extract_entities


def merge_adjacent_entities(entities):
    """Merge consecutive entities that share the same label."""
    if not entities:
        return []

    entities = sorted(entities, key=lambda item: item["start"])
    merged = []

    for entity in entities:
        current = {
            **entity,
            "type": entity.get("type", entity.get("label", "UNKNOWN")),
        }

        if merged:
            previous = merged[-1]

            if (
                current["type"] == previous["type"]
                and current["start"] <= previous["end"] + 1
            ):
                previous["end"] = max(previous["end"], current["end"])
                previous["text"] = (
                    previous["text"] + current["text"]
                )
                previous["score"] = min(
                    previous.get("score", 1.0),
                    current.get("score", 1.0),
                )
                continue

        merged.append(current)

    return merged


def extract_event_times(note):
    """
    Extract simple clock times from the original note.
    These are text-derived times, not independently verified times.
    """
    pattern = re.compile(
        r"\b(?:"
        r"\d{1,2}:\d{2}\s*(?:AM|PM)?"
        r"|"
        r"\d{1,2}\s*(?:AM|PM)"
        r")\b",
        re.IGNORECASE,
    )

    return [
        {
            "text": match.group(0).strip(),
            "start": match.start(),
            "end": match.end(),
        }
        for match in pattern.finditer(note)
    ]


def structure_record(note):
    """Convert a responder note into a structured draft record."""
    entities = merge_adjacent_entities(extract_entities(note))
    event_times = extract_event_times(note)

    medications = []
    unassigned_entities = []
    procedures = []

    medication_entities = [
        entity for entity in entities
        if entity["type"] == "DRUG_NAME"
    ]

    for medication_index, drug in enumerate(medication_entities):
        next_drug_start = (
            medication_entities[medication_index + 1]["start"]
            if medication_index + 1 < len(medication_entities)
            else len(note)
        )

        # Associate extracted attributes occurring after this drug
        # and before the next drug mention.
        attributes = {}

        for entity in entities:
            if (
                entity["type"] != "DRUG_NAME"
                and drug["end"] <= entity["start"] < next_drug_start
            ):
                attributes.setdefault(entity["type"], []).append({
                    "text": entity["text"].strip(),
                    "score": entity.get("score"),
                    "start": entity["start"],
                    "end": entity["end"],
                })

        # Associate the nearest preceding time in the text, if any.
        preceding_times = [
            event_time for event_time in event_times
            if event_time["end"] <= drug["start"]
        ]

        event_timestamp = (
            preceding_times[-1]["text"]
            if preceding_times
            else None
        )

        medications.append({
            "medication_name": drug["text"].strip(),
            "attributes": attributes,
            "source_span": {
                "start": drug["start"],
                "end": drug["end"],
            },
            "event_timestamp": event_timestamp,
            "timestamp_source": (
                "extracted_from_note"
                if event_timestamp
                else "unknown"
            ),
        })

    for entity in entities:
        if entity["type"] == "PROCEDURE":
            procedures.append({
                "procedure_name": entity["text"].strip(),
                "source_span": {
                    "start": entity["start"],
                    "end": entity["end"],
                },
            })
        elif entity["type"] != "DRUG_NAME":
            unassigned_entities.append({
                "text": entity["text"].strip(),
                "type": entity["type"],
                "score": entity.get("score"),
                "start": entity["start"],
                "end": entity["end"],
            })

    return {
        "record_id": str(uuid.uuid4()),
        "original_note": note,
        "record_created_at": datetime.now().astimezone().isoformat(
            timespec="seconds"
        ),
        "medications": medications,
        "unassigned_entities": unassigned_entities,
        "procedures": procedures,
        "status": "draft",
        "reviewed_at": None,
        "finalized_at": None,
        "exported_at": None,
    }
