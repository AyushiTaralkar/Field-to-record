
from transformers import pipeline

MODEL_NAME = "genzeonplatform/healthcare-brain-medication-ner"

def load_ner_model():
    print("Loading medication NER model...")
    ner = pipeline(
        "token-classification",
        model=MODEL_NAME,
        aggregation_strategy="simple"
    )
    print("Model loaded successfully!")
    return ner


if __name__ == "__main__":
    ner = load_ner_model()

    text = "Patient was prescribed 500 mg of paracetamol orally."
    results = ner(text)

    for entity in results:
        print(entity)
