#!/usr/bin/env python
"""
Script to create a Qdrant collection for storing contract retrieval vectors.

This script connects to a running Qdrant server (e.g., the container
defined in docker-compose.yml) and creates a collection with the
appropriate dimension and metric for BGE‑M3 embeddings. By default it
uses a dimension of 1024 and cosine distance. If the collection
already exists, it is left untouched.

Usage:
  python create_collection.py --host <host> --port <port> --collection <name>

Notes:
  • Qdrant supports vector quantization for lower memory usage. To enable
    quantization, specify the `quantized` flag and ensure your server
    supports it. For details see Qdrant documentation.

Requires:
  qdrant-client
"""

import argparse
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create Qdrant collection")
    parser.add_argument("--host", default="localhost", help="Qdrant host")
    parser.add_argument("--port", type=int, default=6333, help="Qdrant port")
    parser.add_argument("--collection", default="contracts", help="Collection name")
    parser.add_argument(
        "--quantized",
        action="store_true",
        help="Use vector quantization (experimental, requires server support)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    client = QdrantClient(host=args.host, port=args.port)
    # Check if collection exists
    collections = client.get_collections().collections
    if any(col.name == args.collection for col in collections):
        print(f"Collection '{args.collection}' already exists. Nothing to do.")
        return
    # Define vector parameters
    params = VectorParams(size=1024, distance=Distance.COSINE)
    # Create collection
    client.create_collection(
        collection_name=args.collection,
        vectors_config=params,
        optimizers_config=None,
        quantization_config="Scalar" if args.quantized else None,
    )
    print(
        f"Collection '{args.collection}' created with dimension 1024 and cosine distance"
        + (" using quantization" if args.quantized else "")
    )


if __name__ == "__main__":
    main()