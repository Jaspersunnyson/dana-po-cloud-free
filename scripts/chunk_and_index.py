#!/usr/bin/env python3
"""
chunk_and_index.py

Given a JSON file produced by `normalize_and_partition.py`, this script
aggregates the document elements into larger "parent" chunks and smaller
"child" chunks, computes BGE‑M3 embeddings for the parent chunks, and
indexes the parents into OpenSearch (for keyword search) and Qdrant (for
vector search). The child chunks are written to a JSON file for use by
downstream retrieval and classification scripts.

Parent chunks are approximately 1.8–2.0k characters long, while child
chunks are approximately 500–700 characters long with 10–15% overlap. The
metadata of each chunk includes the originating document name, page
number(s), and a unique identifier.

Usage:
    python chunk_and_index.py \
        --elements input_elements.json \
        --child-output child_chunks.json \
        --opensearch-index contracts \
        --qdrant-collection chunks

This script assumes that an OpenSearch node is available at
http://opensearch:9200 and a Qdrant instance is reachable at
http://qdrant:6333. If you wish to override these defaults, supply
`--opensearch-host` and `--qdrant-host` arguments.
"""
import argparse
import json
import os
import sys
import uuid
from typing import List, Dict, Any

import numpy as np

try:
    from opensearchpy import OpenSearch, helpers
except ImportError:
    OpenSearch = None  # type: ignore

try:
    from qdrant_client import QdrantClient
except ImportError:
    QdrantClient = None  # type: ignore

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None  # type: ignore

try:
    from langchain.text_splitter import RecursiveCharacterTextSplitter
except ImportError:
    RecursiveCharacterTextSplitter = None  # type: ignore

try:
    # LlamaIndex semantic splitter is optional. If not available, we'll fall back
    # to simple sliding windows for child chunks.
    from llama_index.text_splitter import TokenTextSplitter
    from llama_index import set_global_service_context
    from llama_index.llms import OpenAI
    from llama_index.node_parser import SemanticSplitterNodeParser
except ImportError:
    TokenTextSplitter = None  # type: ignore
    SemanticSplitterNodeParser = None  # type: ignore

DEFAULT_OPENSEARCH_HOST = "opensearch"
DEFAULT_OPENSEARCH_PORT = 9200
DEFAULT_QDRANT_HOST = "qdrant"
DEFAULT_QDRANT_PORT = 6333

PARENT_CHUNK_SIZE = 1900
CHILD_CHUNK_SIZE = 600
CHILD_CHUNK_OVERLAP = 0.15  # 15%


def load_elements(path: str) -> List[Dict[str, Any]]:
    """Load elements from a JSON file."""
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def group_elements_by_doc(elements: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Group elements by their originating document."""
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for el in elements:
        doc = el.get('doc', 'unknown')
        grouped.setdefault(doc, []).append(el)
    # Sort each group's elements by page then by element_id for determinism
    for doc, els in grouped.items():
        els.sort(key=lambda e: (e.get('page', 0), e.get('element_id')))
    return grouped


def build_parent_chunks(grouped: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Assemble parent chunks from grouped elements."""
    parents: List[Dict[str, Any]] = []
    for doc, els in grouped.items():
        buffer: List[str] = []
        meta_list: List[Dict[str, Any]] = []
        current_length = 0
        for el in els:
            text = el.get('text', '')
            # If adding this element would exceed the limit, flush current buffer
            if buffer and current_length + len(text) > PARENT_CHUNK_SIZE:
                parent_id = str(uuid.uuid4())
                combined_text = "\n".join(buffer)
                parents.append({
                    'parent_id': parent_id,
                    'doc': doc,
                    'page': meta_list[0]['page'] if meta_list else 0,
                    'element_ids': [m['element_id'] for m in meta_list],
                    'text': combined_text
                })
                # Reset buffer
                buffer = []
                meta_list = []
                current_length = 0
            # Append current element
            buffer.append(text)
            meta_list.append({'page': el.get('page', 0), 'element_id': el.get('element_id')})
            current_length += len(text)
        # Flush any remaining text as a parent chunk
        if buffer:
            parent_id = str(uuid.uuid4())
            combined_text = "\n".join(buffer)
            parents.append({
                'parent_id': parent_id,
                'doc': doc,
                'page': meta_list[0]['page'] if meta_list else 0,
                'element_ids': [m['element_id'] for m in meta_list],
                'text': combined_text
            })
    return parents


def build_child_chunks(parents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Split parent chunks into smaller child chunks with overlap."""
    children: List[Dict[str, Any]] = []
    for parent in parents:
        text = parent['text']
        doc = parent['doc']
        parent_id = parent['parent_id']
        length = len(text)
        # Determine step size based on overlap
        step = int(CHILD_CHUNK_SIZE * (1 - CHILD_CHUNK_OVERLAP))
        pos = 0
        while pos < length:
            chunk_text = text[pos:pos + CHILD_CHUNK_SIZE]
            child_id = str(uuid.uuid4())
            children.append({
                'child_id': child_id,
                'parent_id': parent_id,
                'doc': doc,
                'text': chunk_text
            })
            pos += step
    return children


def index_to_opensearch(os_client: "OpenSearch", index_name: str, parents: List[Dict[str, Any]]) -> None:
    """Index parent chunks into OpenSearch using bulk API."""
    # Create index with mapping if it does not exist
    if not os_client.indices.exists(index=index_name):
        with open(os.path.join(os.path.dirname(__file__), '..', 'opensearch', 'mapping.json'), 'r', encoding='utf-8') as mfile:
            mapping = json.load(mfile)
        os_client.indices.create(index=index_name, body=mapping)

    actions = []
    for parent in parents:
        actions.append({
            '_index': index_name,
            '_id': parent['parent_id'],
            '_source': {
                'text': parent['text'],
                'doc': parent['doc'],
                'page': parent['page'],
                'parent_id': parent['parent_id'],
                'type': 'parent'
            }
        })
    if actions:
        helpers.bulk(os_client, actions)


def index_to_qdrant(qd_client: "QdrantClient", collection_name: str, parents: List[Dict[str, Any]], model: "SentenceTransformer") -> None:
    """Index parent chunks into Qdrant as vector embeddings."""
    # Create collection if it does not exist
    if collection_name not in [c.name for c in qd_client.get_collections().collections]:
        qd_client.create_collection(
            collection_name=collection_name,
            vectors_config={
                "size": model.get_sentence_embedding_dimension(),
                "distance": "Cosine"
            }
        )
    # Prepare payloads and vectors
    payloads = []
    vectors = []
    ids = []
    for parent in parents:
        ids.append(parent['parent_id'])
        payloads.append({
            'doc': parent['doc'],
            'page': parent['page'],
            'parent_id': parent['parent_id']
        })
        vectors.append(model.encode(parent['text']))
    if ids:
        qd_client.upsert(collection_name=collection_name, ids=ids, vectors=vectors, payloads=payloads)


def save_child_chunks(children: List[Dict[str, Any]], output_path: str) -> None:
    """Write child chunks to a JSON file."""
    with open(output_path, 'w', encoding='utf-8') as f_out:
        json.dump(children, f_out, ensure_ascii=False, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build chunks and index them")
    parser.add_argument("--elements", required=True, help="Path to elements JSON produced by normaliser")
    parser.add_argument("--child-output", required=True, help="Path to write child chunks JSON")
    parser.add_argument("--opensearch-index", default="contracts", help="Name of OpenSearch index to use")
    parser.add_argument("--qdrant-collection", default="chunks", help="Name of Qdrant collection to use")
    parser.add_argument("--opensearch-host", default=DEFAULT_OPENSEARCH_HOST)
    parser.add_argument("--opensearch-port", type=int, default=DEFAULT_OPENSEARCH_PORT)
    parser.add_argument("--qdrant-host", default=DEFAULT_QDRANT_HOST)
    parser.add_argument("--qdrant-port", type=int, default=DEFAULT_QDRANT_PORT)
    args = parser.parse_args()

    elements = load_elements(args.elements)
    grouped = group_elements_by_doc(elements)
    parent_chunks = build_parent_chunks(grouped)
    child_chunks = build_child_chunks(parent_chunks)

    # NOTE:
    # The original implementation attempted to connect to OpenSearch and Qdrant to
    # index parent chunks for keyword and vector search. However, this
    # "cloud‑free" variant deliberately avoids any external services.  The
    # pipeline relies solely on offline retrieval via regex locators (see
    # retrieve_candidates.py) and therefore does not perform indexing.

    # If opensearch‑py or qdrant‑client packages are available, the indexing
    # code will be skipped.  This keeps the dependencies light and allows
    # running the pipeline on GitHub Actions without provisioning remote
    # services.

    # Write child chunks regardless of indexing to feed downstream retrieval.
    save_child_chunks(child_chunks, args.child_output)

if __name__ == "__main__":
    main()