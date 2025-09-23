#!/usr/bin/env python3
"""
normalize_and_partition.py
This script normalises Persian text (digit conversion, character unification, ZWNJ removal)
and partitions input Office or PDF documents into structured elements using the
unstructured library. It outputs a JSON list of elements with associated
metadata such as page number and element identifier.

Usage:
    python normalize_and_partition.py --input input_dir --output output_json

The `input_dir` should contain one or more files (DOCX, PDF, etc.). Each file is
processed independently. The output is a single JSON file containing a list of
elements across all documents.
"""
import argparse
import json
import os
import sys
import uuid
from typing import List, Dict

try:
    # Import unstructured partitioner lazily. This will be installed via
    # requirements.txt.
    from unstructured.partition.auto import partition
except ImportError:
    print("unstructured is required for this script. Please install via requirements.txt.", file=sys.stderr)
    raise

# Translation tables for digit normalisation and character unification.
PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
ENGLISH_DIGITS = "0123456789"
YEH_VARIANTS = "يی"
KAF_VARIANTS = "كک"

def normalize_text(text: str) -> str:
    """Normalise Persian text by converting digits, unifying yeh/kaf and removing ZWNJ."""
    if not text:
        return ""
    # Convert Persian digits to English digits
    translation_table = str.maketrans({p: e for p, e in zip(PERSIAN_DIGITS, ENGLISH_DIGITS)})
    text = text.translate(translation_table)
    # Unify yeh variants to ی and kaf variants to ک
    for variant in YEH_VARIANTS:
        text = text.replace(variant, "ی")  # Farsi Yeh
    for variant in KAF_VARIANTS:
        text = text.replace(variant, "ک")  # Kaf
    # Remove zero‑width non‑joiner (U+200C)
    text = text.replace("\u200c", "")
    return text

def process_file(path: str) -> List[Dict[str, object]]:
    """Partition a single file into elements and normalise their text."""
    elements = partition(filename=path)
    items: List[Dict[str, object]] = []
    for el in elements:
        # Some elements may lack text (e.g., images). Skip them.
        txt = getattr(el, 'text', None)
        if not txt:
            continue
        normalized = normalize_text(txt)
        # Get page number from metadata if available; default to 0
        page_no = 0
        try:
            page_no = int(getattr(el.metadata, 'page_number', 0) or 0)
        except Exception:
            page_no = 0
        items.append({
            "doc": os.path.basename(path),
            "page": page_no,
            "element_id": str(uuid.uuid4()),
            "type": getattr(el, 'category', 'text'),
            "text": normalized
        })
    return items

def main() -> None:
    parser = argparse.ArgumentParser(description="Normalise and partition documents.")
    parser.add_argument("--input", required=True, help="Input directory containing files to process")
    parser.add_argument("--output", required=True, help="Output JSON file to write elements to")
    args = parser.parse_args()

    input_dir = args.input
    output_path = args.output

    if not os.path.isdir(input_dir):
        print(f"Input directory {input_dir} does not exist", file=sys.stderr)
        sys.exit(1)

    all_elements: List[Dict[str, object]] = []
    for fname in os.listdir(input_dir):
        full_path = os.path.join(input_dir, fname)
        if not os.path.isfile(full_path):
            continue
        try:
            file_elements = process_file(full_path)
            all_elements.extend(file_elements)
        except Exception as exc:
            print(f"Error processing {fname}: {exc}", file=sys.stderr)

    with open(output_path, 'w', encoding='utf-8') as f_out:
        json.dump(all_elements, f_out, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()