"""Step 2: brute-force top-k search in NumPy, with Euclidean distance and cosine similarity."""

import json                            # reads and writes the cache files
from pathlib import Path               # handles file paths

import numpy as np  

from vectors.embed import embed        # same Gemini model as the stored vectors
from vectors.search import QUESTIONS   # the same 10 questions as the semantic search

EMBEDDINGS_FILE = Path("vectors/cache/embeddings.jsonl")       # the 372 chunk vectors
QUERIES_FILE = Path("vector_internals/cache/queries.json")     # the 10 question vectors
TOP_K = 5                                               # how many results to keep

def load_chunks():
    """Return the chunk ids and their vectors as one matrix."""
    rows = [json.loads(line) for line in EMBEDDINGS_FILE.open(encoding="utf-8")]
    ids = np.array([row["id"] for row in rows])                          # 0 ... 371
    vectors = np.array([row["vector"] for row in rows], dtype=np.float32)  # one row per chunk
    return ids, vectors

def load_queries():
    """Embed the 10 questions once and save them; later runs just read the file."""
    if QUERIES_FILE.exists():
        return json.loads(QUERIES_FILE.read_text(encoding="utf-8"))
    queries = {q: embed(q) for q in QUESTIONS}        # 10 API calls, first run only
    QUERIES_FILE.parent.mkdir(parents=True, exist_ok=True)
    QUERIES_FILE.write_text(json.dumps(queries), encoding="utf-8") 
    return queries   


def top_k_euclidean(vectors, query, k=TOP_K):
    """Distance from the query to every vector; return the positions and distances of the k smallest."""
    distances = np.linalg.norm(vectors - query, axis=1)    # √(Σ (aᵢ − bᵢ)²) for all 372 rows at once
    best = np.argsort(distances)[:k]                       # positions sorted smallest first, keep k
    return best, distances[best]

def top_k_cosine(vectors, query, k=TOP_K):
    """Cosine from the query to every vector; return the positions and scores of the k biggest."""
    dots = vectors @ query                                             # A · B for all 372 rows at once
    lengths = np.linalg.norm(vectors, axis=1) * np.linalg.norm(query)  # ‖A‖ × ‖B‖ for every row
    scores = dots / lengths                                            # cosine for every row
    best = np.argsort(-scores)[:k]                                     # minus sign = biggest first
    return best, scores[best]


def main() -> None:
    ids, vectors = load_chunks()                               # the 372 chunk ids + their vectors (a 372 × 3,072 matrix)
    queries = load_queries()                                   # the 10 questions + their vectors (from the cache, or the API on the first run)
    print(f"Brute force over {len(ids)} vectors of {vectors.shape[1]} numbers\n")   # heading: "372 vectors of 3072 numbers"

    for question, q in queries.items():                        # take each question and its vector, one at a time
        q = np.array(q, dtype=np.float32)                      # turn the question's 3,072 numbers into a NumPy array
        e_pos, e_dist = top_k_euclidean(vectors, q)            # the 5 closest rows by Euclidean distance + their distances
        c_pos, c_score = top_k_cosine(vectors, q)              # the 5 closest rows by cosine similarity + their scores

        print(f"Q: {question}")                                # print the question
        print(f"  Euclidean ids: {ids[e_pos].tolist()}  distances: {np.round(e_dist, 3).tolist()}")   # row positions → chunk ids; distances to 3 decimals
        print(f"  Cosine    ids: {ids[c_pos].tolist()}  scores:    {np.round(c_score, 3).tolist()}\n")   # same for cosine; \n adds a blank line after


if __name__ == "__main__":
    main()