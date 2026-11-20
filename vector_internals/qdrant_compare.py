"""Step 3: run the same queries in Qdrant and check they match the NumPy results."""

import numpy as np                                                   # array maths
from qdrant_client.models import Distance, PointStruct, VectorParams  # Qdrant building blocks
from vector_internals.brute_force import load_chunks, load_queries, top_k_cosine, top_k_euclidean
from vectors.db import get_client                                    # Qdrant connection

COLLECTION = "payv_internals"

def main() -> None:
    ids, vectors = load_chunks()       # the same 372 vectors 
    queries = load_queries()           # the same 10 question vectors 
    client = get_client()

    # 1. Create a collection where every point has two named vectors:
    # "cosine" (compared by direction) and "euclid" (compared by straight line distance).
    size = vectors.shape[1]                              # numbers per vector: 3,072
    if client.collection_exists(COLLECTION):             # does the test collection already exist
        client.delete_collection(COLLECTION)             # yes: delete it, so every run starts fresh
    client.create_collection(COLLECTION, vectors_config={             # create the collection with two named vector slots:
        "cosine": VectorParams(size=size, distance=Distance.COSINE),  # "cosine" → searched with cosine similarity
        "euclid": VectorParams(size=size, distance=Distance.EUCLID),  # "euclid" → searched with Euclidean distance
    })
    points = [PointStruct(id=int(i), vector={"cosine": v.tolist(), "euclid": v.tolist()})   # one point per chunk, its vector stored in both slots
              for i, v in zip(ids, vectors)]                                                # go through every id with its vector
    client.upload_points(COLLECTION, points=points, wait=True)       # upload all 372 points; wait until Qdrant has saved them

    # 2. Ask NumPy and Qdrant the same questions, and compare their top-5 scores.
    for question, q in queries.items():
        q = np.array(q, dtype=np.float32)
        print(f"Q: {question}")
        for name, numpy_search in [("euclid", top_k_euclidean), ("cosine", top_k_cosine)]:
            pos, numpy_scores = numpy_search(vectors, q)                                       # NumPy top 5
            hits = client.query_points(COLLECTION, query=q.tolist(), using=name, limit=5).points   # Qdrant top 5
            qdrant_scores = [hit.score for hit in hits]
            match = np.allclose(numpy_scores, qdrant_scores, atol=1e-4)                        # equal to 4 decimals?
            print(f"  {name}:  NumPy {ids[pos].tolist()}  Qdrant {[hit.id for hit in hits]}  match: {match}")
        print()


if __name__ == "__main__":
    main()