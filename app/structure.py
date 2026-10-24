
import re
import uuid
from datetime import datetime

from app.ner import extract_entities


ADMINISTRATION_VERBS = re.compile(
    r"\b(administered|given|received|injected|applied|provided)\b",
    re.IGNORECASE,
)

SENTENCE_ENDINGS = ".!?"


def merge_adjacent_entities(entities):
    """Merge overlapping entities with the same label."""
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
                and current["start"] <= previous["end"]
            ):
                if current["end"] > previous["end"]:
                    previous["text"] += current["text"][
                        previous["end"] - current["start"]:
                    ]
                    previous["end"] = current["end"]

                previous["score"] = min(
                    previous.get("score", 1.0),
                    current.get("score", 1.0),
                )
                continue

        merged.append(current)

    return merged


def extract_event_times(note):
    """Extract explicitly mentioned clock times and their source offsets."""
    pattern = re.compile(
        r"(?<!\w)(?:"
        r"\d{1,2}:\d{2}\s*(?:AM|PM)?"
        r"|"
        r"\d{1,2}\s*(?:AM|PM)"
        r")(?!\w)",
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


def get_sentence_bounds(note, position):
    """Return the sentence boundaries around a character position."""
    start = 0
    end = len(note)

    for index in range(position - 1, -1, -1):
        if note[index] in SENTENCE_ENDINGS:
            start = index + 1
            break

    for index in range(position, len(note)):
        if note[index] in SENTENCE_ENDINGS:
            end = index + 1
            break

    # Trim whitespace without changing the original note offsets.
    while start < end and note[start].isspace():
        start += 1

    while end > start and note[end - 1].isspace():
        end -= 1

    return start, end


def get_medication_event_time(note, drug, next_drug_start, event_times):
    """
    Associate a timestamp only when the note provides a reasonable
    sentence-level link to the medication.

    This is a heuristic, not a guarantee of clinical event attribution.
    """
    sentence_start, sentence_end = get_sentence_bounds(
        note, drug["start"]
    )

    sentence_times = [
        event_time
        for event_time in event_times
        if sentence_start <= event_time["start"]
        and event_time["end"] <= sentence_end
    ]

    if not sentence_times:
        return None

    # A time after the medication name in the same sentence is explicit
    # local context, e.g. "Paracetamol was given at 10:30 AM."
    following_times = [
        event_time
        for event_time in sentence_times
        if event_time["start"] >= drug["end"]
    ]

    if following_times:
        return following_times[0]["text"]

    # A time before the medication may apply to it when the same sentence
    # describes an administration event, e.g. "At 10:30 AM, paracetamol
    # was administered."
    preceding_times = [
        event_time
        for event_time in sentence_times
        if event_time["end"] <= drug["start"]
    ]

    if preceding_times:
        sentence = note[sentence_start:sentence_end]

        if ADMINISTRATION_VERBS.search(sentence):
            return preceding_times[-1]["text"]

    return None


def structure_record(note):
    """Convert a responder note into a structured draft for human review."""
    if not isinstance(note, str) or not note.strip():
        raise ValueError("Clinical note cannot be empty.")

    event_times = extract_event_times(note)
    entities = merge_adjacent_entities(extract_entities(note))

    # Remove NER entities overlapping detected clock times. This prevents
    # fragments such as "30 AM" from becoming medication attributes.
    entities = [
        entity
        for entity in entities
        if not any(
            entity["start"] < event_time["end"]
            and entity["end"] > event_time["start"]
            for event_time in event_times
        )
    ]

    medications = []
    unassigned_entities = []
    procedures = []

    medication_entities = [
        entity
        for entity in entities
        if entity["type"] == "DRUG_NAME"
    ]

    assigned_spans = set()

    for medication_index, drug in enumerate(medication_entities):
        next_drug_start = (
            medication_entities[medication_index + 1]["start"]
            if medication_index + 1 < len(medication_entities)
            else len(note)
        )

        attributes = {}

        for entity in entities:
            if entity["type"] in ("DRUG_NAME", "PROCEDURE"):
                continue

            # Preserve the current simple association rule: attributes
            # after this drug and before the next drug mention.
            if drug["end"] <= entity["start"] < next_drug_start:
                attributes.setdefault(entity["type"], []).append({
                    "text": entity["text"].strip(),
                    "score": entity.get("score"),
                    "start": entity["start"],
                    "end": entity["end"],
                })
                assigned_spans.add((entity["start"], entity["end"]))

        event_timestamp = get_medication_event_time(
            note,
            drug,
            next_drug_start,
            event_times,
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
                if event_timestamp is not None
                else "unknown"
            ),
        })

    for entity in entities:
        entity_type = entity["type"]
        span = (entity["start"], entity["end"])

        if entity_type == "DRUG_NAME":
            continue

        if entity_type == "PROCEDURE":
            procedures.append({
                "procedure_name": entity["text"].strip(),
                "source_span": {
                    "start": entity["start"],
                    "end": entity["end"],
                },
            })
            continue

        if span not in assigned_spans:
            unassigned_entities.append({
                "text": entity["text"].strip(),
                "type": entity_type,
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
