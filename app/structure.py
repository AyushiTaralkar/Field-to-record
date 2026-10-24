
from datetime import datetime
from uuid import uuid4

from app.ner import extract_entities


def _entity_text(entity):
    """Return the extracted entity text."""
    return str(entity.get("text", "")).strip()


def _entity_type(entity):
    """Read the entity label returned by the NER model."""
    return str(
        entity.get("type")
        or entity.get("entity")
        or entity.get("entity_group")
        or entity.get("label")
        or ""
    ).upper().replace("B-", "").replace("I-", "")


def _entity_start(entity):
    return entity.get("start")


def _entity_end(entity):
    return entity.get("end")


def _normalise_label(label):
    """Map common medication entity labels to our record schema."""
    aliases = {
        "DRUG": "DRUG_NAME",
        "MEDICATION": "DRUG_NAME",
        "MEDICATION_NAME": "DRUG_NAME",
        "DOSAGE": "STRENGTH",
        "DOSE": "STRENGTH",
        "DRUG_STRENGTH": "STRENGTH",
        "DRUG_ROUTE": "ROUTE",
        "ADMINISTRATION_ROUTE": "ROUTE",
    }

    return aliases.get(label, label)


def _merge_adjacent_entities(entities):
    """
    Merge adjacent fragments with the same label.

    Example:
        '2' + '.' + '5 mg' -> '2.5 mg'

    Character offsets are retained for traceability.
    """
    ordered = sorted(
        entities,
        key=lambda item: (
            item.get("start") is None,
            item.get("start") or 0,
        ),
    )

    merged = []

    for entity in ordered:
        current = dict(entity)
        text = _entity_text(current)

        if not text:
            continue

        current["text"] = text

        if merged:
            previous = merged[-1]
            previous_end = _entity_end(previous)
            current_start = _entity_start(current)

            same_label = (
                _entity_type(previous) == _entity_type(current)
            )

            adjacent = (
                previous_end is not None
                and current_start is not None
                and 0 <= current_start - previous_end <= 2
            )

            if same_label and adjacent:
                previous_text = _entity_text(previous)

                if text in {".", ","}:
                    # Punctuation attaches directly to the preceding text.
                    previous["text"] = previous_text + text
                elif previous_text.endswith((".", ",")):
                    # The next fragment attaches directly after punctuation.
                    previous["text"] = previous_text + text
                else:
                    previous["text"] = previous_text + " " + text

                previous["end"] = _entity_end(current)
                continue

        merged.append(current)

    return merged


def structure_record(note):
    """
    Convert a responder note into a structured draft record.

    This function records extracted information only. It does not
    recommend treatments or validate medication safety.
    """
    note = note.strip()

    if not note:
        raise ValueError("The responder note cannot be empty.")

    raw_entities = extract_entities(note)

    if not isinstance(raw_entities, list):
        raise TypeError(
            "extract_entities(note) must return a list of dictionaries."
        )

    entities = _merge_adjacent_entities(raw_entities)

    medications = []
    unassigned_entities = []
    current_medication = None

    attribute_labels = {
        "STRENGTH",
        "ROUTE",
        "FORM",
        "FREQUENCY",
        "DURATION",
        "REASON",
    }

    for entity in entities:
        text = _entity_text(entity)
        raw_label = _entity_type(entity)
        label = _normalise_label(raw_label)

        if not text or not label:
            continue

        if label == "DRUG_NAME":
            current_medication = {
                "medication_name": text,
                "attributes": {},
                "source_span": {
                    "start": _entity_start(entity),
                    "end": _entity_end(entity),
                },
                "event_timestamp": None,
                "timestamp_source": "unknown",
            }

            medications.append(current_medication)
            continue

        if label in attribute_labels:
            if current_medication is None:
                unassigned_entities.append({
                    "label": label,
                    "text": text,
                    "start": _entity_start(entity),
                    "end": _entity_end(entity),
                })
                continue

            current_medication["attributes"].setdefault(
                label, []
            ).append({
                "text": text,
                "score": entity.get("score"),
                "start": _entity_start(entity),
                "end": _entity_end(entity),
            })

            continue

        unassigned_entities.append({
            "label": label,
            "text": text,
            "start": _entity_start(entity),
            "end": _entity_end(entity),
        })

    return {
        "record_id": str(uuid4()),
        "original_note": note,
        "record_created_at": datetime.now()
        .astimezone()
        .isoformat(timespec="seconds"),
        "medications": medications,
        "unassigned_entities": unassigned_entities,
        "procedures": [],
        "status": "draft",
        "reviewed_at": None,
        "finalized_at": None,
        "exported_at": None,
    }
