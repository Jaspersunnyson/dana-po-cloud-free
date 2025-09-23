#!/usr/bin/env python3
"""
classifier_train.py

Train a multi‑label classifier to predict which clause a child chunk is relevant to.
This script expects a training dataset consisting of child chunks and their
associated clauses. It computes BGE‑M3 embeddings for each chunk and trains a
One‑Vs‑Rest Logistic Regression model. The resulting model is saved to a
joblib file for later use by classifier_infer.py.

The training dataset should be a JSON file where each entry has the keys
`text` and `labels`, where `labels` is a list of clause IDs that the text
contains. An example entry:

    {"text": "متن نمونه", "labels": ["warranty", "hidden_defects"]}

Usage:
    python classifier_train.py --data golden_set/labels.json --model-out model.joblib
"""
import argparse
import json
import joblib
from typing import List, Dict, Any

import numpy as np

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None  # type: ignore

from sklearn.preprocessing import MultiLabelBinarizer
from sklearn.linear_model import LogisticRegression
from sklearn.multiclass import OneVsRestClassifier
from sklearn.calibration import CalibratedClassifierCV


def load_training_data(path: str) -> List[Dict[str, Any]]:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def compute_embeddings(texts: List[str], model: "SentenceTransformer") -> np.ndarray:
    return np.array(model.encode(texts))


def main() -> None:
    parser = argparse.ArgumentParser(description="Train a multi‑label classifier for clause detection")
    parser.add_argument("--data", required=True, help="Path to JSON training data")
    parser.add_argument("--model-out", required=True, help="Path to save the trained model (joblib)")
    args = parser.parse_args()

    if SentenceTransformer is None:
        raise RuntimeError("sentence-transformers library is required for training")

    data = load_training_data(args.data)
    texts = [entry['text'] for entry in data]
    labels = [entry['labels'] for entry in data]

    # Fit label binarizer
    mlb = MultiLabelBinarizer()
    y = mlb.fit_transform(labels)

    # Load embedding model
    try:
        model = SentenceTransformer('BAAI/bge-m3', trust_remote_code=True)
    except Exception:
        model = SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')

    X = compute_embeddings(texts, model)

    # Train one-vs-rest logistic regression and calibrate probabilities
    base_clf = LogisticRegression(max_iter=1000, class_weight='balanced')
    ovr = OneVsRestClassifier(base_clf)
    # Calibrate each classifier
    calibrated = CalibratedClassifierCV(ovr, method='sigmoid', cv=3)
    calibrated.fit(X, y)

    # Save model and label binarizer
    joblib.dump({'model': calibrated, 'mlb': mlb, 'embedding_model': 'BAAI/bge-m3'}, args.model_out)

if __name__ == "__main__":
    main()