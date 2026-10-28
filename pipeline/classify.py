"""Step 5: sort documents by type with TF-IDF + logistic regression (scikit-learn)."""
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline

ROOT = Path(__file__).resolve().parents[1]
GEN = ROOT / "data" / "generated"
MODEL_PATH = ROOT / "models" / "classifier.joblib"
SPLIT_PATH = GEN / "split.json"
CONFIDENCE_THRESHOLD = 0.80   # below this, the document goes to the LLM instead


@dataclass
class Classification:
    doc_type: str
    confidence: float
    confident: bool


def load_dataset() -> tuple[list[str], list[str], list[str]]:
    """Pair every document's text with its true type from the answer keys."""
    ids, texts, labels = [], [], []
    for key_path in sorted((GEN / "answer_keys").glob("*.json")):
        key = json.loads(key_path.read_text())
        ids.append(key["doc_id"])
        labels.append(key["doc_type"])
        texts.append((GEN / "text" / f"{key['doc_id']}.txt").read_text())
    return ids, texts, labels


def build_model():
    return make_pipeline(
        TfidfVectorizer(lowercase=True, ngram_range=(1, 2)),
        LogisticRegression(C=10, max_iter=1000),   # C=10: less regularisation, sharper confidence
    )


def train():
    ids, texts, labels = load_dataset()
    train_ids, test_ids, train_x, test_x, train_y, test_y = train_test_split(
        ids, texts, labels, test_size=0.3, stratify=labels, random_state=42)

    model = build_model().fit(train_x, train_y)
    predictions = model.predict(test_x)

    print(f"Accuracy on {len(test_y)} held-out documents: {accuracy_score(test_y, predictions):.1%}\n")
    print(classification_report(test_y, predictions, zero_division=0))
    print("Confusion matrix (rows = true type, columns = predicted):", [str(c) for c in model.classes_])
    print(confusion_matrix(test_y, predictions, labels=model.classes_))

    confidences = model.predict_proba(test_x).max(axis=1)
    unsure = sum(c < CONFIDENCE_THRESHOLD for c in confidences)
    print(f"\nLowest confidence: {confidences.min():.2f}")
    print(f"Below {CONFIDENCE_THRESHOLD:.0%} (would go to the LLM): {unsure} of {len(test_y)}")

    MODEL_PATH.parent.mkdir(exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    SPLIT_PATH.write_text(json.dumps({"train": train_ids, "test": test_ids}, indent=2))
    print(f"\nSaved model -> {MODEL_PATH}\nSaved train/test split -> {SPLIT_PATH}")
    return model


@lru_cache(maxsize=1)
def load_model():
    return joblib.load(MODEL_PATH)


def classify(text: str, model=None) -> Classification:
    """Return the most likely document type and how sure the model is."""
    model = model or load_model()
    probabilities = model.predict_proba([text])[0]
    best = probabilities.argmax()
    confidence = float(probabilities[best])
    return Classification(str(model.classes_[best]), confidence, confidence >= CONFIDENCE_THRESHOLD)


if __name__ == "__main__":
    train()