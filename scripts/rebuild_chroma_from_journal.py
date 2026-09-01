#!/usr/bin/env python3
"""Rebuild and verify a Chroma collection from its append-only JSONL journal.

The journal is authoritative. Duplicate IDs are accepted only when their
collection, timestamp, and content agree exactly. The output directory must
not already exist, so a failed or suspect rebuild can never overwrite a live
index. Embeddings come from the configured localhost embedding service.
"""

import argparse
import json
import math
import os
from pathlib import Path
import time
import urllib.error
import urllib.request


def load_records(journal_dir, collection_name):
    """Return unique selected-collection records plus audit counters."""
    root = Path(journal_dir)
    if not root.is_dir():
        raise ValueError("journal directory does not exist: %s" % root)
    files = sorted(root.rglob("*.jsonl"))
    if not files:
        raise ValueError("journal contains no .jsonl files")
    records = {}
    rows = duplicates = ignored = 0
    for path in files:
        with path.open(encoding="utf-8", errors="strict") as handle:
            for lineno, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                rows += 1
                try:
                    item = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        "%s:%d is not valid JSON: %s" %
                        (path.relative_to(root), lineno, exc)) from exc
                if not isinstance(item, dict):
                    raise ValueError("%s:%d is not a JSON object" %
                                     (path.relative_to(root), lineno))
                if item.get("collection") != collection_name:
                    ignored += 1
                    continue
                item_id = item.get("id")
                content = item.get("content")
                timestamp = item.get("time")
                if not isinstance(item_id, str) or not item_id:
                    raise ValueError("%s:%d has no string id" %
                                     (path.relative_to(root), lineno))
                if not isinstance(content, str):
                    raise ValueError("%s:%d has no string content" %
                                     (path.relative_to(root), lineno))
                if not isinstance(timestamp, str) or not timestamp:
                    raise ValueError("%s:%d has no string time" %
                                     (path.relative_to(root), lineno))
                normalized = {
                    "id": item_id,
                    "content": content,
                    "time": timestamp,
                    "collection": collection_name,
                }
                previous = records.get(item_id)
                if previous is not None:
                    if previous != normalized:
                        raise ValueError(
                            "conflicting journal records for id %s" % item_id)
                    duplicates += 1
                    continue
                records[item_id] = normalized
    if not records:
        raise ValueError("journal has no records for collection %r" %
                         collection_name)
    return list(records.values()), {
        "source_files": len(files),
        "source_rows": rows,
        "duplicate_rows": duplicates,
        "ignored_other_collection_rows": ignored,
    }


def daemon_health(endpoint, protocol, dimension, timeout):
    with urllib.request.urlopen(
            endpoint.rstrip("/") + "/health", timeout=timeout) as response:
        payload = json.loads(response.read())
    if payload.get("status") != "ready":
        raise RuntimeError("embedding service is not ready: %s" %
                           payload.get("status"))
    if payload.get("protocol") != protocol:
        raise RuntimeError("embedding protocol mismatch: %r != %r" %
                           (payload.get("protocol"), protocol))
    if payload.get("dim") != dimension:
        raise RuntimeError("embedding dimension mismatch: %r != %r" %
                           (payload.get("dim"), dimension))


def embed_batch(endpoint, texts, protocol, dimension, timeout, retries=3):
    body = json.dumps({"texts": texts, "kind": "document"}).encode("utf-8")
    request = urllib.request.Request(
        endpoint.rstrip("/") + "/embed", data=body,
        headers={"Content-Type": "application/json"})
    last_error = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read())
            if payload.get("protocol") != protocol:
                raise RuntimeError("embedding protocol changed during rebuild")
            if payload.get("dim") != dimension:
                raise RuntimeError("embedding dimension changed during rebuild")
            vectors = payload.get("embeddings")
            if not isinstance(vectors, list) or len(vectors) != len(texts):
                raise RuntimeError("embedding service returned the wrong batch size")
            for vector in vectors:
                if (not isinstance(vector, list) or len(vector) != dimension
                        or not all(isinstance(x, (int, float))
                                   and not isinstance(x, bool)
                                   and math.isfinite(x) for x in vector)):
                    raise RuntimeError("embedding service returned an invalid vector")
            return vectors
        except (OSError, ValueError, urllib.error.URLError,
                RuntimeError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(2 ** attempt)
    raise RuntimeError("embedding batch failed after retries: %s" % last_error)


def collection_metadata(args):
    return {
        "embedding_model": args.embedding_model,
        "embedding_backend": "sentence-transformers-daemon",
        "embedding_output_dim": args.dimension,
        "embedding_protocol": args.protocol,
        "embedding_normalized": True,
        "embedding_query_prompt_name": args.query_prompt,
        "hnsw:space": args.metric,
        "hnsw:sync_threshold": args.sync_threshold,
    }


def verify_collection(output_dir, collection_name, records, expected_metadata):
    import chromadb

    client = chromadb.PersistentClient(path=str(output_dir))
    collection = client.get_collection(
        name=collection_name, embedding_function=None)
    expected_ids = {item["id"] for item in records}
    if collection.count() != len(expected_ids):
        raise RuntimeError("collection count differs from journal count")
    stored = collection.get(include=["documents", "metadatas"])
    actual_ids = set(stored.get("ids", []))
    if actual_ids != expected_ids:
        raise RuntimeError(
            "collection IDs differ from journal (missing=%d extra=%d)" %
            (len(expected_ids - actual_ids), len(actual_ids - expected_ids)))
    expected = {item["id"]: item for item in records}
    documents = stored.get("documents", [])
    metadatas = stored.get("metadatas", [])
    if not (len(documents) == len(metadatas) == len(actual_ids)):
        raise RuntimeError("stored document or metadata count is incomplete")
    for index, item_id in enumerate(stored.get("ids", [])):
        if documents[index] != expected[item_id]["content"]:
            raise RuntimeError("stored document differs for id %s" % item_id)
        metadata = metadatas[index] or {}
        if metadata.get("time") != expected[item_id]["time"]:
            raise RuntimeError("stored timestamp differs for id %s" % item_id)
    for key, value in expected_metadata.items():
        if collection.metadata.get(key) != value:
            raise RuntimeError("collection metadata mismatch for %s" % key)

    probe_id = records[0]["id"]
    probe = collection.get(ids=[probe_id], include=["embeddings"])
    embeddings = probe.get("embeddings")
    if embeddings is None or len(embeddings) != 1:
        raise RuntimeError("could not retrieve the verification embedding")
    vector = embeddings[0]
    if hasattr(vector, "tolist"):
        vector = vector.tolist()
    if (len(vector) != expected_metadata["embedding_output_dim"]
            or not all(math.isfinite(float(value)) for value in vector)):
        raise RuntimeError("verification embedding is invalid")
    result = collection.query(
        query_embeddings=[vector], n_results=min(5, len(records)),
        include=["distances"])
    if not result.get("ids") or result["ids"][0][0] != probe_id:
        raise RuntimeError("self-query did not return its own record first")
    distance = result.get("distances", [[None]])[0][0]
    if distance is None or abs(float(distance)) > 1e-5:
        raise RuntimeError("self-query distance is not zero")
    return client


def write_manifest(output_dir, args, audit, record_count, verified):
    manifest = {
        "format": 1,
        "collection": args.collection,
        "record_count": record_count,
        "source_files": audit["source_files"],
        "source_rows": audit["source_rows"],
        "duplicate_rows": audit["duplicate_rows"],
        "ignored_other_collection_rows": audit[
            "ignored_other_collection_rows"],
        "embedding_protocol": args.protocol,
        "embedding_dimension": args.dimension,
        "metric": args.metric,
        "sync_threshold": args.sync_threshold,
        "verified_in_fresh_process": bool(verified),
        "completed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    path = Path(output_dir) / "rebuild-manifest.json"
    temporary = path.with_suffix(".json.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temporary, path)


def build(args, records, audit):
    import chromadb

    output = Path(args.output_dir)
    if output.exists():
        raise ValueError("output directory already exists: %s" % output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir()
    client = chromadb.PersistentClient(path=str(output))
    metadata = collection_metadata(args)
    collection = client.create_collection(
        name=args.collection, metadata=metadata, embedding_function=None)
    for start in range(0, len(records), args.batch_size):
        batch = records[start:start + args.batch_size]
        vectors = embed_batch(
            args.endpoint, [item["content"] for item in batch],
            args.protocol, args.dimension, args.timeout)
        collection.add(
            ids=[item["id"] for item in batch],
            documents=[item["content"] for item in batch],
            embeddings=vectors,
            metadatas=[{"time": item["time"]} for item in batch])
        print("rebuilt %d/%d" % (min(start + len(batch), len(records)),
                                  len(records)), flush=True)
    verify_collection(output, args.collection, records, metadata)
    write_manifest(output, args, audit, len(records), False)
    try:
        client._system.stop()
    except Exception as exc:
        raise RuntimeError("clean Chroma shutdown failed: %s" % exc) from exc


def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--collection", default="memories")
    parser.add_argument("--endpoint", default="http://127.0.0.1:8876")
    parser.add_argument("--protocol", default="qwen3-embedding-8b-1024-v1")
    parser.add_argument("--dimension", type=int, default=1024)
    parser.add_argument("--embedding-model", default="Qwen3-Embedding-8B")
    parser.add_argument("--query-prompt", default="query")
    parser.add_argument("--metric", choices=("cosine", "l2", "ip"),
                        default="cosine")
    parser.add_argument("--sync-threshold", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)
    if not 1 <= args.batch_size <= 16:
        parser.error("--batch-size must be in [1, 16]")
    if args.dimension <= 0:
        parser.error("--dimension must be positive")
    if args.sync_threshold < 2:
        parser.error("--sync-threshold must be at least 2")
    return args


def main(argv=None):
    args = parse_args(argv)
    records, audit = load_records(args.journal_dir, args.collection)
    print("journal: %d rows, %d unique records, %d exact duplicates" %
          (audit["source_rows"], len(records), audit["duplicate_rows"]),
          flush=True)
    metadata = collection_metadata(args)
    if args.verify_only:
        client = verify_collection(
            Path(args.output_dir), args.collection, records, metadata)
        write_manifest(args.output_dir, args, audit, len(records), True)
        try:
            client._system.stop()
        except Exception as exc:
            raise RuntimeError("clean Chroma shutdown failed: %s" % exc) from exc
        print("verified: count, IDs, metadata, and self-query", flush=True)
        return
    daemon_health(args.endpoint, args.protocol, args.dimension, args.timeout)
    build(args, records, audit)
    print("build complete; run once more with --verify-only", flush=True)


if __name__ == "__main__":
    main()
