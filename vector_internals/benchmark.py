"""Step 5: time NumPy brute force against Qdrant (exact and HNSW) for 1,000 and 10,000 vectors."""

import os                                        # read settings from the environment
import time                                      # stopwatch and short waits
from pathlib import Path                         # file paths

import numpy as np                               # brute-force maths
import requests                                  # read Qdrant's own search time
from dotenv import load_dotenv                   # reads the .env file
from qdrant_client import QdrantClient, models   # Qdrant client and its settings

from vector_internals.brute_force import load_queries   # the 10 question vectors (from cache, no API cost)

load_dotenv()                                    # put QDRANT_URL and QDRANT_API_KEY into os.environ

VECTORS_FILE = Path("vector_internals/cache/vectors_10k.npy")   # the 10,000 embedded vectors 
COLLECTION = "payv_benchmark"                    # collection
URL = os.environ["QDRANT_URL"].rstrip("/")       # cluster address
KEY = os.environ["QDRANT_API_KEY"]               # cluster password
client = QdrantClient(url=URL, api_key=KEY, prefer_grpc=True, timeout=300)   # gRPC uploads big vectors faster

def numpy_time(vectors, questions):
    """Average ms for one NumPy brute-force search."""
    start = time.perf_counter()                  # start the stopwatch
    for q in questions:                          # search once for each of the 10 questions
        np.argsort(-(vectors @ q))[:5]           # score every vector, keep the 5 best
    return (time.perf_counter() - start) * 1000 / len(questions)   # total ms ÷ 10 = ms per search

def upload(vectors):
    """Create the collection, upload the vectors, and wait for the HNSW index."""
    if client.collection_exists(COLLECTION):     # left over from an earlier run?
        client.delete_collection(COLLECTION)     # then remove it and start clean
    client.create_collection(                    # make an empty collection
        COLLECTION,                              # its name
        vectors_config=models.VectorParams(size=3072, distance=models.Distance.COSINE),   # 3,072 numbers, cosine
        hnsw_config=models.HnswConfigDiff(full_scan_threshold=10),             # use HNSW even for small data
        optimizers_config=models.OptimizersConfigDiff(indexing_threshold=10),  # build the index straight away
    )
    client.upload_collection(COLLECTION, vectors=vectors, ids=range(len(vectors)),   # ids 0, 1, 2, ... = row numbers
                             batch_size=128, wait=True)                              # 128 vectors per request
    while (client.get_collection(COLLECTION).indexed_vectors_count or 0) < len(vectors):   # index not finished yet?
        time.sleep(2)                            # check again in 2 seconds


def qdrant_time(questions, exact):
    """Average ms Qdrant reports for one search (network time not included)."""
    total = 0                                    # running total of seconds
    for q in questions:                          # each of the 10 questions
        reply = requests.post(f"{URL}/collections/{COLLECTION}/points/query",   # Qdrant's search address
                              headers={"api-key": KEY},                         # log in
                              json={"query": q.tolist(), "limit": 5,            # the question, top 5
                                    "params": {"exact": exact}})                # True = check every vector, False = HNSW
        total += reply.json()["time"]            # Qdrant's own search time, in seconds
    return total * 1000 / len(questions)         # seconds to ms, ÷ 10 = ms per search

def recall(vectors, questions):
    """Share of the true top 5 that HNSW also found."""
    found = 0                                    # matches counted so far
    for q in questions:                          # each of the 10 questions
        true_top5 = set(np.argsort(-(vectors @ q))[:5].tolist())          # NumPy's exact answer (row numbers)
        hnsw_top5 = {p.id for p in client.query_points(COLLECTION, query=q, limit=5).points}   # HNSW's answer (ids)
        found += len(true_top5 & hnsw_top5)      # how many of the 5 both agree on
    return found / (5 * len(questions))          # e.g. 50 of 50 = 1.0 = 100%



def main() -> None:
    all_vectors = np.load(VECTORS_FILE)          # shape (10000, 3072)
    questions = [np.array(q, dtype=np.float32) for q in load_queries().values()]   # 10 question vectors as arrays

    for n in [1_000, 10_000]:                    # test the two sizes
        vectors = all_vectors[:n]                # first 1,000 rows, then all 10,000
        print(f"\nUploading {n:,} vectors and building the HNSW index...")
        upload(vectors)                          # put them in Qdrant and wait for the index
        print(f"  NumPy brute force : {numpy_time(vectors, questions):.2f} ms")
        print(f"  Qdrant exact      : {qdrant_time(questions, exact=True):.2f} ms")
        print(f"  Qdrant HNSW       : {qdrant_time(questions, exact=False):.2f} ms")
        print(f"  HNSW recall@5     : {recall(vectors, questions):.0%}")

    client.delete_collection(COLLECTION)         # clean up the cluster
    print(f"\nDeleted {COLLECTION}")

if __name__ == "__main__":
    main()