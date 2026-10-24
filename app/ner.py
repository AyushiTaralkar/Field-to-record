from transformers import pipeline, AutoTokenizer

MODEL = "genzeonplatform/healthcare-brain-medication-ner"

tokenizer = AutoTokenizer.from_pretrained(MODEL)

nlp = pipeline(
    "token-classification",
    model=MODEL,
    tokenizer=tokenizer,
    aggregation_strategy="first",
)

text = (
    "Responder reports the patient takes Metformin 500 mg "
    "tablet by mouth twice daily for diabetes. "
    "Amoxicillin 500 mg capsule PO three times daily "
    "for seven days was also reported."
)

tokens = tokenizer(
    text,
    add_special_tokens=True,
    truncation=False,
)

print("Original characters:", len(text))
print("Token count:", len(tokens["input_ids"]))
print("Original text:", text)

entities = nlp(text)

for ent in entities:
    print(
        ent["entity_group"],
        repr(ent["word"]),
        ent["start"],
        ent["end"],
        round(ent["score"], 3),
    )