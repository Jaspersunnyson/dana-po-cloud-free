#!/usr/bin/env python3
"""
classifier_infer.py

Use a pre‑trained multi‑label classifier to predict which clauses each child
chunk is relevant to. The classifier is trained on embeddings from the
BGE‑M3 model and saved via joblib. This script reads child chunks, computes
embeddings, applies the classifier to obtain probabilities for each
clause, and outputs a JSON mapping of clauses to candidate chunks along
with their probabilities.

Usage:
    python classifier_infer.py --model model.joblib \
        --child-chunks child_chunks.json \
        --threshold-high 0.55 \
        --threshold-low 0.45 \
        --output predictions.json

If no chunk meets the high threshold for a clause, the script falls back
to including chunks that meet the low threshold. If still no chunks meet
the low threshold, the clause will have an empty list.
"""
import argparse
import json
import joblib
from typing import Dict, Any, List

import numpy as np

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None  # type: ignore


def load_chunks(path: str) -> List[Dict[str, Any]]:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def main() -> None:
    parser = argparse.ArgumentParser(description="Infer clause relevance for child chunks")
    parser.add_argument("--model", required=True, help="Path to trained classifier joblib file")
    parser.add_argument("--child-chunks", required=True, help="Path to JSON with child chunks")
    parser.add_argument("--threshold-high", type=float, default=0.55, help="High probability threshold")
    parser.add_argument("--threshold-low", type=float, default=0.45, help="Low fallback threshold")
    parser.add_argument("--output", required=True, help="Path to write predictions JSON")
    args = parser.parse_args()

    # Load model and label binarizer
    bundle = joblib.load(args.model)
    clf = bundle['model']
    mlb = bundle['mlb']
    # Determine which embedding model to load
    embedding_model_name = bundle.get('embedding_model', 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')
    if SentenceTransformer is None:
        raise RuntimeError("sentence-transformers is not installed for inference")
    try:
        embed_model = SentenceTransformer(embedding_model_name, trust_remote_code=True)
    except Exception:
        embed_model = SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')

    # Load child chunks
    chunks = load_chunks(args.child_chunks)
    texts = [chunk['text'] for chunk in chunks]
    child_ids = [chunk['child_id'] for chunk in chunks]

    # Compute embeddings
    X = np.array(embed_model.encode(texts))
    # Predict probabilities
    probs = clf.predict_proba(X)
    # Convert to dictionary keyed by clause
    clause_names = mlb.classes_.tolist()
    predictions: Dict[str, List[Dict[str, Any]]] = {name: [] for name in clause_names}

    # Fill predictions
    for idx, prob_vec in enumerate(probs):
        for clause_idx, clause_name in enumerate(clause_names):
            prob = prob_vec[clause_idx]
            predictions[clause_name].append({
                'child_id': child_ids[idx],
                'text': texts[idx],
                'probability': float(prob)
            })
    # Filter predictions per clause using thresholds
    final: Dict[str, List[Dict[str, Any]]] = {}
    for clause, preds in predictions.items():
        # Sort descending by probability
        preds.sort(key=lambda x: x['probability'], reverse=True)
        # Try high threshold
        selected = [p for p in preds if p['probability'] >= args.threshold_high]
        if not selected:
            selected = [p for p in preds if p['probability'] >= args.threshold_low]
        final[clause] = selected

    # Write out
    with open(args.output, 'w', encoding='utf-8') as f_out:
        json.dump(final, f_out, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()