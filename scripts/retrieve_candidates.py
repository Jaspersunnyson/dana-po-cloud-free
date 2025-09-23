#!/usr/bin/env python3
"""
retrieve_candidates.py

This script selects candidate child chunks for each clause defined in a
requirements JSON file. It offers two modes of operation:

1. Offline keyword search: When OpenSearch and Qdrant are not available,
   it falls back to a simple keyword scan over the child chunks stored in
   JSON. For each clause, it matches against regex locators defined in
   the requirements and ranks candidates by the number of matches.

2. Hybrid search (optional): If the environment provides OpenSearch and
   Qdrant connections, the script can be extended to perform BM25 +
   vector search, followed by reranking with a cross encoder. This
   fallback implementation leaves placeholders for such integration.

Usage:
    python retrieve_candidates.py \
        --child-chunks child_chunks.json \
        --requirements schemas/requirements_main_IRR.json \
        --output candidates.json

The output JSON maps each clause ID to a list of candidate child
chunks, where each candidate entry includes the child ID and the chunk
text. Only the top N matches (default 50) are kept per clause.
"""
import argparse
import json
import re
from typing import Any, Dict, List


def load_json(path: str) -> Any:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(data: Any, path: str) -> None:
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def compile_clause_patterns(requirements: Dict[str, Any]) -> Dict[str, List[re.Pattern]]:
    """Compile regex patterns for each clause based on its regex_locators field."""
    patterns: Dict[str, List[re.Pattern]] = {}
    for clause in requirements.get('clauses', []):
        clause_id = clause['id']
        regexes = clause.get('regex_locators', [])
        compiled = [re.compile(regex, re.IGNORECASE) for regex in regexes]
        patterns[clause_id] = compiled
    return patterns


def offline_candidate_selection(child_chunks: List[Dict[str, Any]], patterns: Dict[str, List[re.Pattern]], top_k: int = 50) -> Dict[str, List[Dict[str, Any]]]:
    """Select candidate child chunks per clause using simple pattern matching."""
    results: Dict[str, List[Dict[str, Any]]] = {}
    for clause_id, regex_list in patterns.items():
        candidates: List[Dict[str, Any]] = []
        for chunk in child_chunks:
            text = chunk.get('text', '')
            match_count = 0
            for regex in regex_list:
                if regex.search(text):
                    match_count += 1
            if match_count > 0:
                candidates.append({
                    'child_id': chunk['child_id'],
                    'text': text,
                    'match_count': match_count
                })
        # Sort by match count descending and truncate
        candidates.sort(key=lambda x: x['match_count'], reverse=True)
        results[clause_id] = candidates[:top_k]
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Retrieve candidate chunks per clause")
    parser.add_argument("--child-chunks", required=True, help="Path to JSON file containing child chunks")
    parser.add_argument("--requirements", required=True, help="Path to requirements JSON file")
    parser.add_argument("--output", required=True, help="Path to write candidates JSON")
    parser.add_argument("--top-k", type=int, default=50, help="Number of top candidates to keep per clause")
    args = parser.parse_args()

    child_chunks = load_json(args.child_chunks)
    requirements = load_json(args.requirements)
    clause_patterns = compile_clause_patterns(requirements)
    candidates = offline_candidate_selection(child_chunks, clause_patterns, top_k=args.top_k)
    save_json(candidates, args.output)

if __name__ == "__main__":
    main()