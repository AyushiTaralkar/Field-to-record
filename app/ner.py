
from transformers import pipeline, AutoTokenizer
import json

MODEL = "genzeonplatform/healthcare-brain-medication-ner"

# Load the pretrained model once
tokenizer = AutoTokenizer.from_pretrained(MODEL)

nlp = pipeline(
    "token-classification",
    model=MODEL,
    tokenizer=tokenizer,
    aggregation_strategy="first",
)


def extract_entities(text: str) -> list[dict]:
    """Extract medication-related entities from a clinical note."""

    if not isinstance(text, str) or not text.strip():
        raise ValueError("Clinical note cannot be empty.")

    predictions = nlp(text)

    entities = []

    for ent in predictions:
        start = ent["start"]
        end = ent["end"]

        # Recover the exact original text using character offsets.
        original_span = text[start:end]

        entities.append({
            "text": original_span,
            "type": ent["entity_group"],
            "score": round(float(ent["score"]), 4),
            "start": start,
            "end": end,
        })

    return entities


def extract_record(text: str) -> dict:
    """Create a draft record for subsequent human review."""

    entities = extract_entities(text)

    return {
        "original_note": text,
        "entities": entities,
        "status": "draft",
    }


if __name__ == "__main__":
    text = (
        "Responder reports the patient takes Metformin 500 mg "
        "tablet by mouth twice daily for diabetes. "
        "Amoxicillin 500 mg capsule PO three times daily "
        "for seven days was also reported."
    )

    record = extract_record(text)

    print(json.dumps(record, indent=2, ensure_ascii=False))
