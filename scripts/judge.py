#!/usr/bin/env python3
"""
judge.py

Validate and potentially override the structured LLM outputs for each clause
based on simple deterministic checks. The judge looks at the expected text
from the requirements file and the actual text returned by the LLM. If
the LLM claims a PASS but the expected text is not present in the actual
text, the judge overturns the verdict to UNCERTAIN. If the LLM claims a
FAIL but the expected text appears in the actual text, the judge flags
the situation as a conflict for review.

Usage:
    python judge.py --results llm_results.json --requirements requirements.json --output judged_results.json

The input `results` JSON should map clause IDs to dictionaries with keys
`status`, `expected`, `actual`, `evidence`, `fix`, and `severity`. The
output will include additional keys `judge_status` and `judge_reason` for
each clause.
"""
import argparse
import json
from typing import Any, Dict


def load_json(path: str) -> Any:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def judge_clauses(results: Dict[str, Any]) -> Dict[str, Any]:
    """Apply judge logic to each clause in the results dict."""
    judged: Dict[str, Any] = {}
    for clause_id, data in results.items():
        # Copy original data
        clause_result = dict(data)
        status = clause_result.get('status')
        expected = clause_result.get('expected', '')
        actual = clause_result.get('actual', '') or ''
        judge_status = status
        judge_reason = ''
        if status == 'PASS':
            # Overturn PASS to UNCERTAIN if expected string not in actual
            if expected and expected not in actual:
                judge_status = 'UNCERTAIN'
                judge_reason = 'Expected text not found in actual text'
        elif status == 'FAIL':
            # Flag conflict if expected appears in actual
            if expected and expected in actual:
                judge_status = 'CONFLICT'
                judge_reason = 'Expected text found despite FAIL verdict'
        # Attach judge verdict
        clause_result['judge_status'] = judge_status
        if judge_reason:
            clause_result['judge_reason'] = judge_reason
        judged[clause_id] = clause_result
    return judged


def main() -> None:
    parser = argparse.ArgumentParser(description="Judge LLM results")
    parser.add_argument("--results", required=True, help="Path to LLM results JSON")
    parser.add_argument("--requirements", required=True, help="Path to requirements JSON (unused in current version)")
    parser.add_argument("--output", required=True, help="Path to output judged JSON")
    args = parser.parse_args()

    results = load_json(args.results)
    judged = judge_clauses(results)
    with open(args.output, 'w', encoding='utf-8') as f_out:
        json.dump(judged, f_out, ensure_ascii=False, indent=2)

if __name__ == '__main__':
    main()