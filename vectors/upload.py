"""Step 4: create the Qdrant collection and upload every chunk as a point."""

import json                       # reads the embeddings file
from pathlib import Path          # handles file paths

from qdrant_client.models import Distance, PayloadSchemaType, PointStruct, VectorParams   
from vectors.db import get_client   # connection function

COLLECTION = "payv_corpus"                         # name of the new collection
DIMENSIONS = 3072                                  # numbers per vector (Gemini Embedding 2)
IN_FILE = Path("vectors/cache/embeddings.jsonl")   # input: chunks + vectors

def main() -> None:
    client = get_client()                                                      # connect to Qdrant Cloud
    rows = [json.loads(line) for line in IN_FILE.open(encoding="utf-8")]       # all 372 chunks with vectors

    # Start fresh: if collection already exists (from an earlier run), delete it.
    # other other collections are not touched.
    if client.collection_exists(COLLECTION):
        client.delete_collection(COLLECTION)

    client.create_collection(
        collection_name=COLLECTION,
        vectors_config=VectorParams(size=DIMENSIONS, distance=Distance.COSINE),
    )

    # Index the doc_type field so filtered searches ("only playbooks") are fast.
    client.create_payload_index(
        collection_name=COLLECTION,
        field_name="doc_type",
        field_schema=PayloadSchemaType.KEYWORD,    # KEYWORD = exact text values like "playbooks"
    )

    # Turn each row into a Qdrant point: id + vector + payload (the labels).
    points = [
        PointStruct(
            id=row["id"],                          # 0 to 371
            vector=row["vector"],                  # the 3,072 numbers
            payload={
                "source": row["source"],           # which document it came from
                "title": row["title"],             # the document's title
                "doc_type": row["doc_type"],       
                "chunk": row["chunk"],             # chunk number inside the document
                "text": row["text"],               # the chunk text, shown in search results
            },
        )
        for row in rows
    ]

    # Upload in batches of 64 points; wait=True waits until Qdrant has saved them.
    client.upload_points(collection_name=COLLECTION, points=points, batch_size=64, wait=True)

    # Check: ask Qdrant how many points the collection now holds.
    count = client.count(collection_name=COLLECTION, exact=True).count
    print(f"Uploaded {count} points to '{COLLECTION}' (size {DIMENSIONS}, cosine)")


if __name__ == "__main__":
    main()